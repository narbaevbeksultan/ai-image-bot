# 🚀 Настройка ngrok для тестирования Betatransfer callback

## 📋 **Что такое ngrok:**
ngrok создает туннель к вашему локальному серверу, делая его доступным из интернета через временный URL.

## 🔧 **Установка ngrok:**

### **Windows:**
1. **Скачайте** с https://ngrok.com/download
2. **Распакуйте** в папку (например, `C:\ngrok`)
3. **Добавьте в PATH** или запускайте из папки

### **macOS/Linux:**
```bash
# Через Homebrew (macOS)
brew install ngrok

# Или скачайте вручную
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
tar -xzf ngrok-v3-stable-linux-amd64.tgz
```

## 🚀 **Запуск callback сервера:**

### **1. Установите зависимости:**
```bash
pip install -r requirements.txt
```

### **2. Запустите callback сервер:**
```bash
python callback_server.py
```

**Результат:**
```
Callback сервер запущен на порту 5000
URL для callback: http://localhost:5000/payment/callback
```

## 🌐 **Запуск ngrok туннеля:**

### **Откройте новый терминал и выполните:**
```bash
ngrok http 5000
```

**Результат:**
```
Forwarding    https://abc123.ngrok.io -> http://localhost:5000
```

## ⚙️ **Настройка callback URL в Betatransfer:**

### **В личном кабинете Betatransfer заполните:**
- **URL оповещения:** `https://abc123.ngrok.io/payment/callback`
- **URL успеха:** `https://abc123.ngrok.io/payment/success`
- **URL неуспеха:** `https://abc123.ngrok.io/payment/fail`

## 🔄 **Обновите .env файл:**

```env
# Замените на полученный ngrok URL
WEBHOOK_BASE_URL=https://abc123.ngrok.io
```

## 🧪 **Тестирование:**

### **1. Проверьте API подключение:**
```bash
python test_betatransfer.py
```

### **2. Проверьте callback сервер:**
```bash
curl https://abc123.ngrok.io/health
```

## ⚠️ **Важные моменты:**

1. **ngrok URL меняется** при каждом перезапуске
2. **Обновляйте URL** в Betatransfer при изменении
3. **Используйте только для тестирования**
4. **Для продакшена купите домен**

## 🎯 **Следующие шаги:**

1. ✅ Создать `.env` файл
2. ✅ Установить ngrok
3. ✅ Запустить callback сервер
4. ✅ Получить ngrok URL
5. ✅ Настроить callback в Betatransfer
6. ✅ Протестировать создание платежа

## 📞 **Поддержка:**

- **ngrok:** https://ngrok.com/docs
- **Betatransfer:** support@betatransfer.io
