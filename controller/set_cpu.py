"""
Programmatic version of `docker update --cpus`.
This is the actuator your (later) proactive controller will call.

Usage: python set_cpu.py fl-worker-1 1.0
"""
import sys
import docker

PERIOD = 100_000  # microseconds, must match cpu_period in compose


def set_cpus(name: str, cpus: float) -> None:
    c = docker.from_env().containers.get(name)
    c.update(cpu_period=PERIOD, cpu_quota=int(cpus * PERIOD))
    c.reload()
    q = c.attrs["HostConfig"]["CpuQuota"]
    print(f"{name}: cpu limit now {q / PERIOD:.2f} CPU")


if __name__ == "__main__":
    set_cpus(sys.argv[1], float(sys.argv[2]))
