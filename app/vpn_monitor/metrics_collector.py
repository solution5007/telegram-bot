import psutil
import csv
import time
import os
from datetime import datetime

# Определяем путь к папку, где лежит сам скрипт
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_NAME = os.path.join(BASE_DIR, 'vps_metrics.csv')
INTERVAL = 60  # Секунд

def get_metrics():
    return {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'cpu_usage': psutil.cpu_percent(interval=1),
        'ram_usage': psutil.virtual_memory().percent,
        'disk_usage': psutil.disk_usage('/').percent,
        'net_sent': psutil.net_io_counters().bytes_sent,
        'net_recv': psutil.net_io_counters().bytes_recv,
        'process_count': len(psutil.pids())
    }

def main():
    file_exists = os.path.isfile(FILE_NAME)
    print(f"Сбор данных запущен. Файл: {FILE_NAME}")
    
    try:
        while True:
            metrics = get_metrics()
            with open(FILE_NAME, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=metrics.keys())
                if not file_exists:
                    writer.writeheader()
                    file_exists = True
                writer.writerow(metrics)
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\nОстановка...")

if __name__ == "__main__":
    main()
