# monitoring

This folder holds the configuration of the monitoring stack in `docker-compose.yml`. cAdvisor reads the CPU of every container, Prometheus stores it and Grafana shows it.

- `prometheus.yml`: scrapes cAdvisor every 5 s, and HAProxy while a live run is going. It also stores samples up to 3 h late, which helps after clock jumps.
- `grafana/provisioning/datasources/prometheus.yml`: makes Prometheus Grafana's data source.
- `grafana/provisioning/dashboards/demo.yml`: loads the dashboards that `docker-compose.yml` mounts.
- `grafana/dashboards/autoscaler-live.json`: the dashboard "Live autoscaler demo (step 4B)".
- `grafana/dashboards/demo.json`: earlier part, the dashboard "CPU allocation demo".
- `grafana/dashboards/proactive-autoscaling.json`: earlier part, an exported dashboard that is not loaded automatically.
