#!/usr/bin/env python3

import os
import argparse
import requests
from google import genai


# ==========================================
# Configuration
# ==========================================
PROMETHEUS_URL = "http://localhost:9090"  # Replace with your actual Prometheus endpoint
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
LONG_PERIOD = "7d"


# ==========================================
# 1. Prometheus Query Helper
# ==========================================
def query_prometheus(query):
    """Executes a PromQL query against the Prometheus API."""
    try:
        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={'query': query}
        )
        response.raise_for_status()
        return response.json().get('data', {}).get('result', [])
    except Exception as e:
        print(f"Error querying Prometheus for '{query}': {e}")
        return []


def build_promql_filters(clusters, namespaces, extra_labels=None):
    """Dynamically builds PromQL label matchers based on user input."""
    labels = []
    if extra_labels:
        for k, v in extra_labels.items():
            labels.append(f'{k}="{v}"')

    if clusters:
        labels.append(f'cluster=~"{"|".join(clusters)}"')

    if namespaces:
        labels.append(f'namespace=~"{"|".join(namespaces)}"')

    if labels:
        return "{" + ", ".join(labels) + "}"
    return ""


# ==========================================
# 2. Fetch Metrics (GitLab Runner Rules)
# ==========================================
def gather_cluster_metrics(clusters, namespaces):
    print("Gathering GitLab CI/CD metrics using pre-calculated Recording Rules...")

    # Default to gitlab-runner namespace if none provided
    if not namespaces:
        namespaces = ["gitlab-runner"]

    base_filters = build_promql_filters(clusters, namespaces)
    cpu_req_filters = build_promql_filters(clusters, namespaces, {"resource": "cpu"})
    mem_req_filters = build_promql_filters(clusters, namespaces, {"resource": "memory"})

    metrics_data = {}

    # Query 1: Max CPU Usage
    cpu_max_query = f'gitlab_job_container_resource_usage_cpu_cores_max:1w{base_filters}'
    for result in query_prometheus(cpu_max_query):
        labels = result['metric']
        key = f"{labels.get('cluster')}/{labels.get('namespace')}/{labels.get('label_gitlab_project')}/{labels.get('label_gitlab_job_name')}/{labels.get('container')}"
        if key not in metrics_data: metrics_data[key] = {"labels": labels}
        metrics_data[key]["cpu_max_cores"] = round(float(result['value'][1]), 4)

    # Query 2: Current CPU Requests
    cpu_req_query = f'gitlab_job_container_resource_requests{cpu_req_filters}'
    for result in query_prometheus(cpu_req_query):
        labels = result['metric']
        key = f"{labels.get('cluster')}/{labels.get('namespace')}/{labels.get('label_gitlab_project')}/{labels.get('label_gitlab_job_name')}/{labels.get('container')}"
        if key in metrics_data:
            metrics_data[key]["cpu_request_cores"] = round(float(result['value'][1]), 4)

    # Query 3: Max Memory Usage
    mem_max_query = f'gitlab_job_container_resource_usage_memory_bytes_max:1w{base_filters}'
    for result in query_prometheus(mem_max_query):
        labels = result['metric']
        key = f"{labels.get('cluster')}/{labels.get('namespace')}/{labels.get('label_gitlab_project')}/{labels.get('label_gitlab_job_name')}/{labels.get('container')}"
        if key not in metrics_data: metrics_data[key] = {"labels": labels}
        metrics_data[key]["memory_max_mib"] = round(float(result['value'][1]) / (1024 * 1024), 2)

    # Query 4: Current Memory Requests
    mem_req_query = f'gitlab_job_container_resource_requests{mem_req_filters}'
    for result in query_prometheus(mem_req_query):
        labels = result['metric']
        key = f"{labels.get('cluster')}/{labels.get('namespace')}/{labels.get('label_gitlab_project')}/{labels.get('label_gitlab_job_name')}/{labels.get('container')}"
        if key in metrics_data:
            metrics_data[key]["memory_request_mib"] = round(float(result['value'][1]) / (1024 * 1024), 2)

    # Query 5: OOM Killed Events
    oom_query = f'gitlab_job_container_resource_usage_memory_oom_killed{base_filters}'
    for result in query_prometheus(oom_query):
        labels = result['metric']
        key = f"{labels.get('cluster')}/{labels.get('namespace')}/{labels.get('label_gitlab_project')}/{labels.get('label_gitlab_job_name')}/{labels.get('container')}"
        if key in metrics_data:
            metrics_data[key]["oom_kill_events"] = int(result['value'][1])

    return metrics_data


# ==========================================
# 3. Ask Gemini for Recommendations
# ==========================================
def get_ai_recommendations(metrics_data):
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY environment variable not set.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Updated CSV Headers for GitLab
    csv_lines = ["Cluster,Namespace,Project,JobName,Container,CPU_Max,CPU_Req,Mem_Max_MiB,Mem_Req_MiB,OOM_Kills"]
    skipped_count = 0

    for key, data in metrics_data.items():
        raw_cpu_req = data.get("cpu_request_cores", 0.0)
        raw_mem_req = data.get("memory_request_mib", 0.0)

        try:
            cpu_req = float(raw_cpu_req) if raw_cpu_req else 0.0
            mem_req = float(raw_mem_req) if raw_mem_req else 0.0
        except ValueError:
            cpu_req = 0.0
            mem_req = 0.0

        if mem_req <= 256.0 and cpu_req <= 0.050:
            skipped_count += 1
            continue

        labels = data.get("labels", {})
        cluster = labels.get("cluster", "N/A")
        ns = labels.get("namespace", "N/A")
        project = labels.get("label_gitlab_project", "N/A")
        job = labels.get("label_gitlab_job_name", "N/A")
        c = labels.get("container", "N/A")

        cpu_max = data.get("cpu_max_cores", "")
        mem_max = data.get("memory_max_mib", "")
        oom_kills = data.get("oom_kill_events", 0)

        line = f"{cluster},{ns},{project},{job},{c},{cpu_max},{cpu_req},{mem_max},{mem_req},{oom_kills}"
        csv_lines.append(line)

    csv_payload = "\n".join(csv_lines)
    containers_to_analyze = len(csv_lines) - 1

    prompt = f"""
    You are an expert Kubernetes administrator and cloud cost optimization specialist.
    I have extracted container resource usage metrics from CI/CD GitLab Runner pipelines over the last {LONG_PERIOD}.

    Here is the telemetry data in CSV format:
    {csv_payload}

    CRITICAL INSTRUCTIONS:
    1. Analyze the data but ONLY output the Top 30 most critical CI/CD jobs that need tuning (prioritize highest wasted cost / over-provisioning, or highest OOM kill risk).
    2. Format your entire response as a SINGLE Markdown table. Do not write introductory or concluding paragraphs.
    3. Use the following columns: Cluster | Project | Job Name | Container | New CPU Req | New Mem Limit | Reason
    4. Keep the 'Reason' column to a maximum of 5 words.

    Rules for tuning CI/CD jobs:
    - Memory is in MiB. Suggest memory limits in MiB.
    - CPU is in cores.
    - If OOM kills > 0, raise memory limit.
    - If max usage is far below requests, lower requests to save pipeline costs.
    """

    print(f"\nOptimization Stats:")
    print(f"- Skipped {skipped_count} tiny containers.")
    print(f"- Sending {containers_to_analyze} significant jobs to Gemini for analysis...\n")

    if containers_to_analyze == 0:
        print("No containers met the minimum resource thresholds. Exiting.")
        return

    response = client.models.generate_content_stream(
        model='gemini-2.5-flash',
        contents=prompt,
    )

    print("--- AI Recommendations ---")
    for chunk in response:
        print(chunk.text, end="", flush=True)
    print("\n--------------------------")


# ==========================================
# Execution
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GitLab Runner AI Resource Optimizer")
    parser.add_argument("-c", "--clusters", nargs="*", default=[], help="List of clusters to analyze. Defaults to all.")
    parser.add_argument("-n", "--namespaces", nargs="*", default=["gitlab-runner"], help="List of namespaces. Defaults to 'gitlab-runner'.")

    args = parser.parse_args()

    print(f"Target Clusters: {', '.join(args.clusters) if args.clusters else 'ALL'}")
    print(f"Target Namespaces: {', '.join(args.namespaces)}")

    k8s_data = gather_cluster_metrics(args.clusters, args.namespaces)

    if not k8s_data:
        print("No metrics gathered. Please check your Prometheus URL and ensure gitlab pipelines have run recently.")
    else:
        get_ai_recommendations(k8s_data)
