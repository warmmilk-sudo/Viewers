import paramiko
import time

def make_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('172.16.82.11', port=22, username='root123', password='root123',
                   timeout=15, look_for_keys=False, allow_agent=False)
    return client

def run(cmd, timeout=20):
    print(f'\n=== {cmd[:80]} ===')
    try:
        client = make_client()
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode(errors='replace')
        err = stderr.read().decode(errors='replace')
        client.close()
        if out: print(out[:5000])
        if err: print('STDERR:', err[:500])
    except Exception as e:
        print(f'ERROR: {e}')
    time.sleep(0.5)

# Write new nginx.conf to a temp file then copy into container
nginx_conf = '''events {
    worker_connections 1024;
}

http {
    map $http_upgrade $connection_upgrade {
        default upgrade;
        '' close;
    }

    server {
        listen 80;

        # OHIF Viewer (webpack dev server)
        location / {
            proxy_pass http://host.docker.internal:3001;
            proxy_http_version 1.1;
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Port $server_port;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_read_timeout 600s;
            proxy_send_timeout 600s;
        }

        # dcm4chee-arc DICOMweb API
        location /dcm4chee-arc/ {
            proxy_pass http://arc:8080/dcm4chee-arc/;
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Port $server_port;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            client_max_body_size 0;
        }
    }
}
'''

# Write to temp file on server
run(f'cat > /tmp/nginx_new.conf << \'NGINXEOF\'\n{nginx_conf}\nNGINXEOF')
run('echo root123 | sudo -S docker cp /tmp/nginx_new.conf pacs-gateway:/etc/nginx/nginx.conf 2>&1')
run('echo root123 | sudo -S docker exec pacs-gateway nginx -t 2>&1')
run('echo root123 | sudo -S docker exec pacs-gateway nginx -s reload 2>&1')
# Test after reload
run('curl -m5 -s -o /dev/null -w "%{http_code}" http://localhost:18081/ 2>&1')
run('curl -m5 -s -o /dev/null -w "%{http_code}" "http://localhost:18081/dcm4chee-arc/aets/DCM4CHEE/rs/studies?limit=1" 2>&1')
