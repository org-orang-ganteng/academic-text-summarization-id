# Gunicorn configuration file
import multiprocessing

# Server socket
bind = "127.0.0.1:5000"

# Worker processes
workers = 2
worker_class = "gthread"
threads = 4
timeout = 300  # 5 menit, untuk model abstractive yang lambat

# Logging
accesslog = "/var/log/nlp-summarization/access.log"
errorlog = "/var/log/nlp-summarization/error.log"
loglevel = "info"

# Process naming
proc_name = "nlp-summarization"

# Preload app to share model across workers
preload_app = True
