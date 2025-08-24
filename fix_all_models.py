#!/usr/bin/env python3
"""
Скрипт для автоматического исправления всех моделей генерации изображений
Заменяет простые вызовы replicate.run на асинхронные с asyncio.wait_for
"""

import re

def fix_model_calls(file_path):
    """Исправляет все вызовы replicate.run для моделей генерации изображений"""
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Список моделей для исправления
    models = [
        "google/imagen-4-ultra",
        "luma/photon", 
        "recraft-ai/recraft-v3-svg",
        "bria-ai/bria-3.2"
    ]
    
    # Паттерн для поиска простых вызовов replicate.run
    pattern = r'(\s+)(output = replicate\.run\(\s*"([^"]+)"\s*,\s*input=\{[^}]+\}\s*\))'
    
    def replace_match(match):
        indent = match.group(1)
        old_call = match.group(2)
        model = match.group(3)
        
        # Проверяем, является ли это моделью для исправления
        if any(m in model for m in models):
            new_call = f'''{indent}loop = asyncio.get_event_loop()
{indent}output = await asyncio.wait_for(
{indent}    loop.run_in_executor(None, lambda: replicate.run(
{indent}        "{model}",
{indent}        input={{prompt_with_style, **replicate_params}}
{indent}    )),
{indent}    timeout=60.0
{indent})'''
            return new_call
        else:
            return old_call
    
    # Заменяем все совпадения
    new_content = re.sub(pattern, replace_match, content)
    
    # Добавляем обработку TimeoutError для всех исправленных блоков
    for model_name in ["Google Imagen 4 Ultra", "Luma Photon", "Recraft AI", "Bria 3.2"]:
        # Ищем блоки с except Exception as e:
        pattern = r'(\s+elif selected_model == \'' + model_name + r'\':[^}]+except Exception as e:)'
        
        def add_timeout_handling(match):
            block = match.group(1)
            # Добавляем обработку TimeoutError перед except Exception
            timeout_handler = f'''{indent}                except asyncio.TimeoutError:
{indent}                    await send_text(update, context, "⏰ Превышено время ожидания генерации {model_name} (60 сек)")
{indent}                    return
{indent}                '''
            return block.replace("except Exception as e:", timeout_handler + "except Exception as e:")
        
        new_content = re.sub(pattern, add_timeout_handling, new_content)
    
    # Записываем исправленный файл
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"✅ Файл {file_path} исправлен!")
    print("🔧 Все модели теперь используют асинхронные вызовы с таймаутом")

if __name__ == "__main__":
    fix_model_calls("bot.py")
    print("\n🎉 Все модели исправлены! Теперь нужно:")
    print("1. Перезапустить бота на Railway")
    print("2. Протестировать генерацию изображений")
