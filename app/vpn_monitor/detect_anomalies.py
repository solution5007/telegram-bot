import pandas as pd
from sklearn.ensemble import IsolationForest
import os
from pathlib import Path


def detect_anomalies(csv_file=None):
    """
    Обнаруживает аномалии в метриках VPS используя Isolation Forest.
    
    Args:
        csv_file: Путь к CSV файлу с метриками. Если не указан, использует путь по умолчанию.
    
    Returns:
        str: Отформатированный результат анализа для вывода в чат админа.
    """
    if csv_file is None:
        # Получаем директорию текущего скрипта
        FILE_NAME = Path(__file__).parent / 'vps_metrics.csv'
    else:
        FILE_NAME = Path(csv_file)
    
    if not FILE_NAME.exists():
        return f"❌ Файл метрик не найден: {FILE_NAME}\n\nУбедитесь, что metrics_collector.py запущен."
    
    try:
        df = pd.read_csv(FILE_NAME)
        
        if df.empty:
            return "⚠️ Файл метрик пуст. Дождитесь накопления данных."
        
        # Подготовка данных для анализа
        # Берём только числовые колонки (исключаем timestamp)
        X = df.drop(columns=['timestamp'])
        
        # Обучение модели Isolation Forest
        # contamination - это ожидаемая доля аномалий (примерно 2%)
        model = IsolationForest(contamination=0.02, random_state=42)
        model.fit(X)
        
        # Поиск аномалий
        # 1 - нормально, -1 - аномалия
        df['anomaly_score'] = model.predict(X)
        
        # Вывод результатов
        anomalies = df[df['anomaly_score'] == -1]
        
        result = "📊 <b>Результаты анализа аномалий:</b>\n\n"
        result += f"📈 Всего записей: {len(df)}\n"
        result += f"⚠️ Обнаружено аномалий: {len(anomalies)}\n"
        result += f"✅ Нормальных записей: {len(df) - len(anomalies)}\n\n"
        
        if not anomalies.empty:
            result += "🚨 <b>Последние 5 аномалий:</b>\n<pre>"
            # Форматируем последние 5 аномалий
            for idx, row in anomalies[['timestamp', 'cpu_usage', 'ram_usage', 'disk_usage']].tail(5).iterrows():
                result += f"\n⏰ {row['timestamp']}"
                result += f"\n   CPU: {row['cpu_usage']:.1f}% | RAM: {row['ram_usage']:.1f}% | DISK: {row['disk_usage']:.1f}%"
            result += "</pre>\n"
        else:
            result += "✅ Аномалии не обнаружены. Система работает стабильно!\n"
        
        return result
        
    except Exception as e:
        return f"❌ Ошибка при анализе: {str(e)}"


if __name__ == "__main__":
    # Для прямого запуска скрипта
    print(detect_anomalies())
