# Исправленная версия bot.py с правильной структурой try-except

# Основная проблема была в нарушенной структуре try-except для Bytedance
# Нужно добавить недостающий except блок между строками 9488-9504

# Вот что нужно исправить в оригинальном bot.py:

"""
# НАЙТИ ЭТО (около строки 9488):
                            continue

                            

                    except asyncio.TimeoutError:

                        logging.warning(f"Таймаут при генерации через Bytedance (180 сек)")

                        if send_text:

                            await send_text(f"⏰ Таймаут при генерации нативного 2K изображения\n💡 Seedream-3 требует до 3 минут для максимального качества. Попробуйте выбрать другую модель или попробовать снова")

                        continue

                        

                except Exception as e:

# И ЗАМЕНИТЬ НА ЭТО:
                            continue

                        # Добавляем изображение в список для отправки
                        if image_url:
                            media.append(InputMediaPhoto(media=image_url, caption=f"Сгенерировано: {topic}"))
                            print(f"🔍 Bytedance: добавлено изображение в media группу: {image_url[:100]}...")
                        else:
                            print(f"🔍 Bytedance: не удалось получить URL изображения")

                    except asyncio.TimeoutError:

                        logging.warning(f"Таймаут при генерации через Bytedance (180 сек)")

                        if send_text:

                            await send_text(f"⏰ Таймаут при генерации нативного 2K изображения\n💡 Seedream-3 требует до 3 минут для максимального качества. Попробуйте выбрать другую модель или попробовать снова")

                        continue

                        

                except Exception as e:
"""

# ИЛИ ПРОСТО УДАЛИТЬ ДУБЛИРОВАННЫЙ КОД:
# Удалить строки 9239-9241 где есть дублированное логирование для Bytedance
