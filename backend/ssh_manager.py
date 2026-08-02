import paramiko
import os

class SSHManager:
    def __init__(self, hostname, username, key_path):
        self.hostname = hostname
        self.username = username
        self.key_path = key_path
        self.client = None

    # In ssh_manager.py
class SSHManager:
    # ... existing __init__ and connect ...

    def execute_and_stream(self, command, callback):
        if not self.client:
            self.connect()
        
        # We use a combined command to ensure output is captured correctly
        stdin, stdout, stderr = self.client.exec_command(command)
        
        # Stream both stdout and stderr
        for line in iter(stdout.readline, ""):
            callback(line.strip())
        
        return stdout.channel.recv_exit_status()

    def connect(self):
        """Establishes the connection."""
        self.client = paramiko.SSHClient()
        # Automatically add the server's host key
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            hostname=self.hostname,
            username=self.username,
            key_filename=self.key_path
        )

    def execute_command(self, command):
        """Executes a command and returns output."""
        if not self.client:
            self.connect()
        
        stdin, stdout, stderr = self.client.exec_command(command)
        
        # Read the outputs
        exit_status = stdout.channel.recv_exit_status()
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        
        return {
            "exit_status": exit_status,
            "stdout": output,
            "stderr": error
        }

    def close(self):
        if self.client:
            self.client.close()

# Example Usage:
# vps = SSHManager("123.45.67.89", "root", "/path/to/id_rsa")
# result = vps.execute_command("apt-get update && apt-get install -y nginx")
# print(result['stdout'])