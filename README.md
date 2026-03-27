# Kubernetes Resource Optimizer Dashboard

A complete observability stack to help you "right-size" your Kubernetes workloads. This repository contains heavily optimized Prometheus recording rules and a highly visual Grafana dashboard designed to instantly highlight CPU and Memory waste across multiple clusters.

**Acknowledgments:**
> The Prometheus recording rules in this repository build upon the foundation provided by [arvatoaws-labs/k8soptimizer](https://github.com/arvatoaws-labs/k8soptimizer) project. We have adapted them for Thanos compatibility and multi-cluster environments.

---

## ✨ Key Features

* **Multi-Cluster & Thanos Ready:** Safely handles duplicate metric series and `group_left` cardinality issues common in federated Thanos environments.
* **Over-provisioning Heatmaps:** The Grafana table dynamically colors cells red or orange when a container's requested CPU or Memory heavily exceeds its historical maximum usage.
* **Historical Baselines:** Easily toggle between 1d, 3d, 7d, 14d, and 30d lookback windows to compare static configuration limits against actual historical traffic spikes.
* **Zero-Spam Dashboards:** Cleanly organizes everything by Cluster -> Namespace -> Workload -> Container.

---

## 🚀 Installation & Setup

### 1. Deploy the Prometheus Rules
To make the dashboard work, Prometheus needs to calculate the historical data. Apply the `prometheus-rules.yaml` file to your cluster.

⚠️ **CRITICAL: Check your Prometheus Operator Labels!**
Before applying the file, you must ensure the `release` label in the YAML matches your Prometheus Operator's `ruleSelector`. If they do not match, Prometheus will silently ignore the file.

Check your cluster's required label:
```bash
kubectl get prometheus -n <your-monitoring-namespace> -o yaml | grep -A 5 ruleSelector
```

Update the metadata.labels in the prometheus-rules.yaml file to match that output, then apply it:
```bash
kubectl apply -f rules/prometheus-rules.yaml
```

 Gemini said

Here is a complete, ready-to-use README.md file for your repository. It includes the exact reference to the original k8soptimizer project, explains the features you built, and explicitly highlights the ruleSelector label trap we successfully debugged!

You can copy and paste this directly into your GitHub repository:
Markdown

# Kubernetes Resource Optimizer Dashboard

A complete observability stack to help you "right-size" your Kubernetes workloads. This repository contains heavily optimized Prometheus recording rules and a highly visual Grafana dashboard designed to instantly highlight CPU and Memory waste across multiple clusters.

**Acknowledgments:**
> The Prometheus recording rules in this repository build upon the foundation provided by the excellent [arvatoaws-labs/k8soptimizer](https://github.com/arvatoaws-labs/k8soptimizer) project. We have adapted them for Thanos compatibility and multi-cluster environments.

---

## ✨ Key Features

* **Multi-Cluster & Thanos Ready:** Safely handles duplicate metric series and `group_left` cardinality issues common in federated Thanos environments.
* **Over-provisioning Heatmaps:** The Grafana table dynamically colors cells red or orange when a container's requested CPU or Memory heavily exceeds its historical maximum usage.
* **Historical Baselines:** Easily toggle between 1d, 3d, 7d, 14d, and 30d lookback windows to compare static configuration limits against actual historical traffic spikes.
* **Zero-Spam Dashboards:** Cleanly organizes everything by Cluster -> Namespace -> Workload -> Container.

---

## 🚀 Installation & Setup

### 1. Deploy the Prometheus Rules
To make the dashboard work, Prometheus needs to calculate the historical data. Apply the `prometheus-rules.yaml` file to your cluster.

⚠️ **CRITICAL: Check your Prometheus Operator Labels!**
Before applying the file, you must ensure the `release` label in the YAML matches your Prometheus Operator's `ruleSelector`. If they do not match, Prometheus will silently ignore the file.

Check your cluster's required label:
```bash
kubectl get prometheus -n <your-monitoring-namespace> -o yaml | grep -A 5 ruleSelector
```

Update the metadata.labels in the prometheus-rules.yaml file to match that output, then apply it:
```bash
kubectl apply -f rules/prometheus-rules.yaml
```

### 2. Import the Grafana Dashboard

* Open your Grafana instance.
* Navigate to Dashboards -> New -> Import.
* Upload the `k8soptimizer-dashboard.json` file from the `dashboards/` directory of this repo.
* Select your Prometheus or Thanos data source from the dropdown and click Import.

---

## 📊 How to read the Dashboard Heatmaps

The Historical Baseline table at the center of the dashboard does the heavy lifting for you using built-in ratio calculations:

* Green/Transparent Background: The workload is well-tuned. Resource requests are close to actual historical maximums.
* Orange Background: The workload is over-provisioned. The container is requesting up to 150% more resources than it has ever used in the selected time period.
* Red Background: Severe waste. The container is requesting more than 200% of its historical maximum usage.
* Purple Text (Limits): If the CPU or Memory Limit text turns purple, your hard limit is exactly equal to your maximum recorded usage, meaning the pod is likely being throttled or is at risk of an OOMKill during the next traffic spike.

---

# Contributing

Feel free to open issues or submit pull requests if you have ideas to make the queries faster or the dashboard even more intuitive!
