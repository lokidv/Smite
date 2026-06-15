#!/usr/bin/env python3
"""
Smite Node CLI
"""
import os
import sys
import subprocess
import argparse
import shutil
from pathlib import Path


NODE_SERVICE = "smite-node"
NODE_UNIT_PATH = Path("/etc/systemd/system/smite-node.service")
NATIVE_NODE_DIR = Path("/opt/smite-node")


def is_native_node():
    """Detect a native (systemd + venv) install rather than a Docker install."""
    if NODE_UNIT_PATH.exists():
        return True
    return (NATIVE_NODE_DIR / ".venv" / "bin" / "python").exists()


def get_compose_file():
    """Get docker-compose file path"""
    possible_roots = [
        Path("/opt/smite-node"),
        Path("/usr/local/node"),  # Legacy installation path
        Path.cwd(),
        Path(__file__).parent.parent / "node",
    ]
    
    for node_dir in possible_roots:
        compose_file = node_dir / "docker-compose.yml"
        if compose_file.exists():
            return compose_file
    
    return Path("/opt/smite-node") / "docker-compose.yml"


def get_env_file():
    """Get .env file path"""
    possible_roots = [
        Path("/etc/smite-node"),  # Native installation config dir
        Path("/opt/smite-node"),
        Path("/usr/local/node"),  # Legacy installation path
        Path.cwd(),
        Path(__file__).parent.parent / "node",
    ]
    
    for node_dir in possible_roots:
        env_file = node_dir / ".env"
        if env_file.exists():
            return env_file
    
    if is_native_node():
        return Path("/etc/smite-node") / ".env"
    return Path("/opt/smite-node") / ".env"


def run_docker_compose(args, capture_output=False):
    """Run docker compose command"""
    compose_file = get_compose_file()
    if not compose_file.exists():
        print(f"Error: docker-compose.yml not found at {compose_file}")
        print(f"\nPlease ensure you're in the node directory or docker-compose.yml exists at:")
        print(f"  - /opt/smite-node/docker-compose.yml")
        print(f"  - /usr/local/node/docker-compose.yml")
        print(f"  - {Path.cwd()}/docker-compose.yml")
        sys.exit(1)
    
    # Change to the directory containing docker-compose.yml so relative paths work
    compose_dir = compose_file.parent
    original_cwd = Path.cwd()
    
    try:
        os.chdir(compose_dir)
        cmd = ["docker", "compose", "-f", str(compose_file)] + args
        result = subprocess.run(cmd, capture_output=capture_output, text=True, cwd=str(compose_dir))
        if not capture_output and result.returncode != 0:
            sys.exit(result.returncode)
        return result
    finally:
        os.chdir(original_cwd)


def cmd_status(args):
    """Show node status"""
    print("Node Status:")
    print("-" * 50)
    
    if is_native_node():
        result = subprocess.run(["systemctl", "is-active", NODE_SERVICE], capture_output=True, text=True)
        state = result.stdout.strip() or "unknown"
        print(f"Service (systemd): {state}")
    else:
        result = subprocess.run(["docker", "ps", "--filter", "name=smite-node", "--format", "{{.Status}}"], 
                              capture_output=True, text=True)
        if result.stdout.strip():
            print(f"Docker: {result.stdout.strip()}")
        else:
            print("Docker: Not running")
    
    try:
        try:
            import requests
        except ImportError:
            print("API: requests library not installed")
            return
            
        env_file = get_env_file()
        port = 8888
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("NODE_API_PORT="):
                    port = int(line.split("=")[1])
        
        response = requests.get(f"http://localhost:{port}/api/agent/status", timeout=2)
        if response.status_code == 200:
            data = response.json()
            print(f"API: Running")
            print(f"Active Tunnels: {data.get('active_tunnels', 0)}")
        else:
            print("API: Not responding")
    except Exception as e:
        print(f"API: Not accessible ({e})")


def cmd_update(args):
    """Update node (pull images and recreate)"""
    if is_native_node():
        print("Native (offline) install detected.")
        print("To update, build a new offline bundle (scripts/build-offline-bundle.sh),")
        print("transfer it to this server, extract it, and run: sudo bash scripts/install-node-native.sh")
        print("\nRestarting service with current version...")
        subprocess.run(["systemctl", "restart", NODE_SERVICE], check=False)
        print("Node restarted.")
        return
    
    print("Updating node...")
    compose_file = get_compose_file()
    node_dir = compose_file.parent
    
    if (node_dir / ".git").exists():
        print("Pulling latest changes from git...")
        subprocess.run(["git", "pull"], cwd=node_dir, check=False)
        if (node_dir / "docker-compose.yml").exists():
            print("docker-compose.yml updated from git")
    else:
        print("Downloading latest docker-compose.yml...")
        try:
            import urllib.request
            compose_url = "https://raw.githubusercontent.com/lokidv/Smite/main/node/docker-compose.yml"
            urllib.request.urlretrieve(compose_url, node_dir / "docker-compose.yml")
            print("docker-compose.yml updated")
        except Exception as e:
            print(f"Warning: Could not update docker-compose.yml: {e}")
    
    run_docker_compose(["pull"])
    run_docker_compose(["up", "-d", "--force-recreate"])
    print("Node updated.")


def cmd_restart(args):
    """Restart node (recreate container to pick up .env changes, no pull)"""
    print("Restarting node...")
    
    if is_native_node():
        result = subprocess.run(["systemctl", "restart", NODE_SERVICE], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Failed to restart {NODE_SERVICE}: {result.stderr.strip()}")
            print(f"Check logs with: journalctl -u {NODE_SERVICE} -n 50 --no-pager")
            sys.exit(result.returncode)
        print("Node restarted. Tunnels will be restored by the panel.")
        return
    
    run_docker_compose(["stop", "smite-node"])
    run_docker_compose(["rm", "-f", "smite-node"])
    result = run_docker_compose(["up", "-d", "--no-deps", "--no-pull", "smite-node"], capture_output=True)
    if result.returncode != 0 and "--no-pull" in result.stderr:
        run_docker_compose(["up", "-d", "--no-deps", "smite-node"])
    else:
        if result.returncode != 0:
            print(result.stderr)
            sys.exit(result.returncode)
    print("Node restarted. Tunnels will be restored by the panel.")


def cmd_edit(args):
    """Edit docker-compose.yml (Docker) or the systemd unit (native)"""
    editor = os.environ.get("EDITOR", "nano")
    
    if is_native_node():
        subprocess.run([editor, str(NODE_UNIT_PATH)])
        subprocess.run(["systemctl", "daemon-reload"], check=False)
        print("Run 'smite-node restart' to apply changes.")
        return
    
    compose_file = get_compose_file()
    subprocess.run([editor, str(compose_file)])


def cmd_edit_env(args):
    """Edit .env file"""
    env_file = get_env_file()
    if not env_file.exists():
        print(f".env file not found. Creating...")
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("")
    
    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, str(env_file)])


def cmd_logs(args):
    """Stream logs"""
    if is_native_node():
        cmd = ["journalctl", "-u", NODE_SERVICE, "--no-pager", "-n", "200"]
        if args.follow:
            cmd.append("-f")
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            pass
        return
    
    follow = ["--follow"] if args.follow else []
    run_docker_compose(["logs"] + follow + ["smite-node"])


def cmd_uninstall(args):
    """Uninstall Smite Node - removes everything"""
    if is_native_node():
        print("=" * 60)
        print("⚠️  WARNING: This will completely remove Smite Node (native install)!")
        print("=" * 60)
        print("\nThis will remove:")
        print("  - systemd service (smite-node)")
        print("  - Installation directory (/opt/smite-node)")
        print("  - Configuration directory (/etc/smite-node)")
        print("  - Data directory (/var/lib/smite-node)")
        print("  - CLI script (/usr/local/bin/smite-node)")
        print("\n⚠️  ALL DATA WILL BE LOST!")
        print("=" * 60)
        
        response = input("\nAre you sure you want to continue? Type 'yes' to confirm: ")
        if response.lower() != 'yes':
            print("Uninstall cancelled.")
            sys.exit(0)
        
        print("\n[1/3] Stopping and removing systemd service...")
        subprocess.run(["systemctl", "disable", "--now", NODE_SERVICE], capture_output=True, check=False)
        try:
            NODE_UNIT_PATH.unlink()
        except OSError:
            pass
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, check=False)
        print("  ✓ Service removed")
        
        print("\n[2/3] Removing directories...")
        for d in [Path("/opt/smite-node"), Path("/etc/smite-node"), Path("/var/lib/smite-node")]:
            if d.exists():
                try:
                    shutil.rmtree(d)
                    print(f"  ✓ Removed {d}")
                except Exception as e:
                    print(f"  ⚠️  Warning: Could not remove {d}: {e}")
            else:
                print(f"  - {d} does not exist")
        
        print("\n[3/3] Removing CLI script...")
        cli_path = Path("/usr/local/bin/smite-node")
        if cli_path.exists():
            try:
                cli_path.unlink()
                print("  ✓ Removed /usr/local/bin/smite-node")
            except Exception as e:
                print(f"  ⚠️  Warning: Could not remove CLI script: {e}")
        
        print("\n" + "=" * 60)
        print("✅ Smite Node has been completely uninstalled!")
        print("=" * 60)
        return
    
    print("=" * 60)
    print("⚠️  WARNING: This will completely remove Smite Node!")
    print("=" * 60)
    print("\nThis will remove:")
    print("  - All Docker containers (smite-node)")
    print("  - All Docker volumes")
    print("  - Installation directory (/opt/smite-node)")
    print("  - CLI script (/usr/local/bin/smite-node)")
    print("  - Docker images (ghcr.io/lokidv/smite-node)")
    print("\n⚠️  ALL DATA WILL BE LOST!")
    print("=" * 60)
    
    response = input("\nAre you sure you want to continue? Type 'yes' to confirm: ")
    if response.lower() != 'yes':
        print("Uninstall cancelled.")
        sys.exit(0)
    
    print("\nStarting uninstall...")
    
    print("\n[1/5] Stopping and removing containers...")
    try:
        compose_file = get_compose_file()
        if compose_file.exists():
            compose_dir = compose_file.parent
            original_cwd = Path.cwd()
            try:
                os.chdir(compose_dir)
                subprocess.run(["docker", "compose", "-f", str(compose_file), "down", "-v"], 
                             capture_output=True, check=False)
            finally:
                os.chdir(original_cwd)
        
        subprocess.run(["docker", "stop", "smite-node"], capture_output=True, check=False)
        subprocess.run(["docker", "rm", "-f", "smite-node"], capture_output=True, check=False)
        print("  ✓ Containers removed")
    except Exception as e:
        print(f"  ⚠️  Warning: {e}")
    
    print("\n[2/5] Removing Docker volumes...")
    try:
        result = subprocess.run(["docker", "volume", "ls", "-q", "--filter", "name=smite-node"], 
                              capture_output=True, text=True)
        volumes = result.stdout.strip().split('\n')
        for volume in volumes:
            if volume:
                subprocess.run(["docker", "volume", "rm", "-f", volume], capture_output=True, check=False)
        print("  ✓ Volumes removed")
    except Exception as e:
        print(f"  ⚠️  Warning: {e}")
    
    print("\n[3/5] Removing Docker images...")
    try:
        subprocess.run(["docker", "rmi", "-f", "ghcr.io/lokidv/smite-node"], capture_output=True, check=False)
        subprocess.run(["docker", "rmi", "-f", "ghcr.io/lokidv/smite-node:latest"], capture_output=True, check=False)
        result = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}", "ghcr.io/lokidv/smite-node"], 
                              capture_output=True, text=True)
        for tag in result.stdout.strip().split('\n'):
            if tag:
                subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, check=False)
        print("  ✓ Images removed")
    except Exception as e:
        print(f"  ⚠️  Warning: {e}")
    
    print("\n[4/5] Removing installation directory...")
    install_dirs = [Path("/opt/smite-node"), Path("/usr/local/node")]
    for install_dir in install_dirs:
        if install_dir.exists():
            try:
                shutil.rmtree(install_dir)
                print(f"  ✓ Removed {install_dir}")
            except Exception as e:
                print(f"  ⚠️  Warning: Could not remove {install_dir}: {e}")
        else:
            print(f"  - {install_dir} does not exist")
    
    print("\n[5/5] Removing CLI script...")
    cli_path = Path("/usr/local/bin/smite-node")
    if cli_path.exists():
        try:
            cli_path.unlink()
            print("  ✓ Removed /usr/local/bin/smite-node")
        except Exception as e:
            print(f"  ⚠️  Warning: Could not remove CLI script: {e}")
    else:
        print("  - CLI script not found")
    
    print("\n" + "=" * 60)
    print("✅ Smite Node has been completely uninstalled!")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Smite Node CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    subparsers.add_parser("status", help="Show node status")
    
    subparsers.add_parser("update", help="Update node (pull images and recreate)")
    
    subparsers.add_parser("restart", help="Restart node (recreate to pick up .env changes)")
    
    subparsers.add_parser("edit", help="Edit docker-compose.yml")
    
    subparsers.add_parser("edit-env", help="Edit .env file")
    
    logs_parser = subparsers.add_parser("logs", help="View logs")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow logs")
    
    subparsers.add_parser("uninstall", help="Completely remove Smite Node")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == "status":
        cmd_status(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "restart":
        cmd_restart(args)
    elif args.command == "edit":
        cmd_edit(args)
    elif args.command == "edit-env":
        cmd_edit_env(args)
    elif args.command == "logs":
        cmd_logs(args)
    elif args.command == "uninstall":
        cmd_uninstall(args)


if __name__ == "__main__":
    main()

