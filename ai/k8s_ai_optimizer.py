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
# 2. Fetch Metrics (Updated for Recording Rules)
# ==========================================
def gather_cluster_metrics(clusters, namespaces):
    print("Gathering metrics using pre-calculated Recording Rules...")

    # Build the dynamic filter strings
    base_filters = build_promql_filters(clusters, namespaces)
    cpu_req_filters = build_promql_filters(clusters, namespaces, {"resource": "cpu"})
    mem_req_filters = build_promql_filters(clusters, namespaces, {"resource": "memory"})

    metrics_data = {}

    # Query 1: Max CPU Usage (using the 1w recording rule)
    cpu_max_query = f'kube_workload_container_resource_usage_cpu_cores_max:1w{base_filters}'
    for result in query_prometheus(cpu_max_query):
        labels = result['metric']
        key = f"{labels.get('cluster')}/{labels.get('namespace')}/{labels.get('workload')}/{labels.get('container')}"
        if key not in metrics_data: metrics_data[key] = {"labels": labels}
        metrics_data[key]["cpu_max_cores"] = round(float(result['value'][1]), 4)

    # Query 2: Current CPU Requests (using pre-joined recording rule)
    cpu_req_query = f'kube_workload_container_resource_requests{cpu_req_filters}'
    for result in query_prometheus(cpu_req_query):
        labels = result['metric']
        key = f"{labels.get('cluster')}/{labels.get('namespace')}/{labels.get('workload')}/{labels.get('container')}"
        if key in metrics_data:
            metrics_data[key]["cpu_request_cores"] = round(float(result['value'][1]), 4)

    # Query 3: Max Memory Usage (using the 1w recording rule)
    mem_max_query = f'kube_workload_container_resource_usage_memory_bytes_max:1w{base_filters}'
    for result in query_prometheus(mem_max_query):
        labels = result['metric']
        key = f"{labels.get('cluster')}/{labels.get('namespace')}/{labels.get('workload')}/{labels.get('container')}"
        if key not in metrics_data: metrics_data[key] = {"labels": labels}
        metrics_data[key]["memory_max_mib"] = round(float(result['value'][1]) / (1024 * 1024), 2)

    # Query 4: Current Memory Requests (using pre-joined recording rule)
    mem_req_query = f'kube_workload_container_resource_requests{mem_req_filters}'
    for result in query_prometheus(mem_req_query):
        labels = result['metric']
        key = f"{labels.get('cluster')}/{labels.get('namespace')}/{labels.get('workload')}/{labels.get('container')}"
        if key in metrics_data:
            metrics_data[key]["memory_request_mib"] = round(float(result['value'][1]) / (1024 * 1024), 2)

    # Query 5: OOM Killed Events
    oom_query = f'kube_workload_container_resource_usage_memory_oom_killed{base_filters}'
    for result in query_prometheus(oom_query):
        labels = result['metric']
        key = f"{labels.get('cluster')}/{labels.get('namespace')}/{labels.get('workload')}/{labels.get('container')}"
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

    csv_lines = ["Cluster,Namespace,Workload,Container,CPU_Max,CPU_Req,Mem_Max_MiB,Mem_Req_MiB,OOM_Kills"]
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
        wl = labels.get("workload", "N/A")
        c = labels.get("container", "N/A")

        cpu_max = data.get("cpu_max_cores", "")
        mem_max = data.get("memory_max_mib", "")
        oom_kills = data.get("oom_kill_events", 0)

        line = f"{cluster},{ns},{wl},{c},{cpu_max},{cpu_req},{mem_max},{mem_req},{oom_kills}"
        csv_lines.append(line)

    csv_payload = "\n".join(csv_lines)
    containers_to_analyze = len(csv_lines) - 1

    prompt = f"""
    You are an expert Kubernetes administrator and cloud cost optimization specialist.
    I have extracted container resource usage metrics from multiple clusters over the last {LONG_PERIOD}.

    Here is the telemetry data in CSV format:
    {csv_payload}

    CRITICAL INSTRUCTIONS:
    1. Analyze the data but ONLY output the Top 30 most critical containers that need tuning (prioritize highest wasted cost / over-provisioning, or highest OOM kill risk).
    2. Format your entire response as a SINGLE Markdown table. Do not write introductory or concluding paragraphs.
    3. Use the following columns: Cluster | Namespace | Workload | Container | New CPU Req | New Mem Limit | Reason
    4. Keep the 'Reason' column to a maximum of 5 words.

    Rules for tuning:
    - Memory is in MiB. Suggest memory limits in MiB.
    - CPU is in cores.
    - If OOM kills > 0, raise memory limit.
    - If max usage is far below requests, lower requests.
    """

    print(f"\nOptimization Stats:")
    print(f"- Skipped {skipped_count} tiny containers.")
    print(f"- Sending {containers_to_analyze} significant containers to Gemini for analysis...\n")

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
    parser = argparse.ArgumentParser(description="K8s AI Resource Optimizer")
    parser.add_argument("-c", "--clusters", nargs="*", default=[], help="List of clusters to analyze (e.g., -c cluster1 cluster2). Defaults to all.")
    parser.add_argument("-n", "--namespaces", nargs="*", default=[], help="List of namespaces to analyze (e.g., -n default kube-system). Defaults to all.")

    args = parser.parse_args()

    print(f"Target Clusters: {', '.join(args.clusters) if args.clusters else 'ALL'}")
    print(f"Target Namespaces: {', '.join(args.namespaces) if args.namespaces else 'ALL'}")

    k8s_data = gather_cluster_metrics(args.clusters, args.namespaces)

    if not k8s_data:
        print("No metrics gathered. Please check your Prometheus URL and queries.")
    else:
        get_ai_recommendations(k8s_data)
