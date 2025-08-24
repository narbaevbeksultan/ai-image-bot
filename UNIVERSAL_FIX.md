# 🔧 УНИВЕРСАЛЬНОЕ РЕШЕНИЕ - Копируем логику Ideogram для всех моделей

## 🎯 ПРОБЛЕМА НАЙДЕНА!

**Разница между работающими и неработающими моделями:**

### ✅ Ideogram (работает):
```python
output = await asyncio.wait_for(
    loop.run_in_executor(None, lambda: replicate.run(
        "ideogram-ai/ideogram-v3-turbo",
        input={"prompt": prompt_with_style, **replicate_params}
    )),
    timeout=60.0
)

# Специальная обработка итераторов
if hasattr(output, '__iter__') and not isinstance(output, str):
    try:
        output_list = list(output)
        if output_list:
            image_url = output_list[0]
    except Exception as e:
        # Обработка ошибок
```

### ❌ Google Imagen, Luma Photon, Recraft AI (не работают):
```python
output = replicate.run(
    "google/imagen-4-ultra",
    input={"prompt": prompt_with_style, **replicate_params}
)

# Простая обработка без учета особенностей моделей
```

## 🚀 РЕШЕНИЕ:

### Шаг 1: Унифицировать вызовы
Заменить простые `replicate.run()` на асинхронные вызовы с таймаутом

### Шаг 2: Скопировать логику обработки
Применить **специальную обработку итераторов** из Ideogram ко всем моделям

### Шаг 3: Добавить проверки
Добавить проверки формата данных для каждой модели

## 🛠️ КОНКРЕТНЫЕ ИЗМЕНЕНИЯ:

### Для Google Imagen 4 Ultra:
```python
# БЫЛО:
output = replicate.run("google/imagen-4-ultra", ...)

# СТАЛО:
output = await asyncio.wait_for(
    loop.run_in_executor(None, lambda: replicate.run(
        "google/imagen-4-ultra",
        input={"prompt": prompt_with_style, **replicate_params}
    )),
    timeout=60.0
)
```

### Для Luma Photon:
```python
# БЫЛО:
output = replicate.run("luma/photon", ...)

# СТАЛО:
output = await asyncio.wait_for(
    loop.run_in_executor(None, lambda: replicate.run(
        "luma/photon",
        input={"prompt": prompt_with_style, **replicate_params}
    )),
    timeout=60.0
)
```

### Для Recraft AI:
```python
# БЫЛО:
output = replicate.run("recraft-ai/recraft-v3-svg", ...)

# СТАЛО:
output = await asyncio.wait_for(
    loop.run_in_executor(None, lambda: replicate.run(
        "recraft-ai/recraft-v3-svg",
        input={"prompt": prompt_with_style, **replicate_params}
    )),
    timeout=60.0
)
```

## 🎉 ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:

После унификации:
- ✅ **Все модели** будут использовать **одинаковую логику обработки**
- ✅ **Все модели** будут **корректно обрабатывать итераторы**
- ✅ **Все модели** будут **возвращать правильные URL**
- ✅ **Все модели** будут **отображать изображения в Telegram**

---
**Проблема: разные модели используют разную логику обработки**  
**Решение: унифицировать по образцу работающего Ideogram** 🚀

