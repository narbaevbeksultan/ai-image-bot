# Конфигурация цен для AI Image Generator Bot

# Пакеты кредитов (pay-per-use модель)
CREDIT_PACKAGES = {
    'small': {
        'name': '🪙 Малый пакет',
        'credits': 2000,
        'price': 14.0,
        'currency': 'UAH',
        'price_per_credit': 0.007,
        'description': '2000 кредитов для начала работы'
    },
    'medium': {
        'name': '🪙 Средний пакет',
        'credits': 5000,
        'price': 30.0,
        'currency': 'UAH',
        'price_per_credit': 0.006,
        'description': '5000 кредитов со скидкой 14%'
    },
    'large': {
        'name': '🪙 Большой пакет',
        'credits': 10000,
        'price': 50.0,
        'currency': 'UAH',
        'price_per_credit': 0.005,
        'description': '10000 кредитов со скидкой 29%'
    }
}

# Стоимость генераций по моделям (в кредитах)
GENERATION_COSTS = {
    'Ideogram': 10,
    'Bytedance (Seedream-3)': 10,
    'Luma Photon': 10,
    'Bria 3.2': 12,
    'Google Imagen 4 Ultra': 16,
    'Recraft AI': 20,
    'FLUX.1 Kontext Pro': 12  # Редактирование изображений
}

# Стоимость генераций видео Bytedance (в кредитах)
VIDEO_GENERATION_COSTS = {
    'Bytedance 480p 5s': 37,
    'Bytedance 720p 5s': 71,
    'Bytedance 1080p 5s': 172,
    'Bytedance 480p 10s': 71,
    'Bytedance 720p 10s': 138,
    'Bytedance 1080p 10s': 342
}

# Стоимость генераций по форматам (дополнительно к модели)
FORMAT_COSTS = {
    'Instagram Reels': 0,
    'TikTok': 0,
    'YouTube Shorts': 0,
    'Instagram Post': 0,
    'Instagram Stories': 0,
    'Изображения': 0,
    'custom': 0
}

# Бесплатные лимиты для новых пользователей
FREE_LIMITS = {
    'total_generations': 3,  # Всего 3 бесплатные генерации навсегда
    'models_available': ['Ideogram'],  # Только базовая модель
    'formats_available': ['Instagram Post', 'Изображения']  # Базовые форматы
}

# Настройки валют
CURRENCY_SETTINGS = {
    'UAH': {
        'symbol': '₴',
        'name': 'Украинская гривна',
        'exchange_rate': 1.0
    },
    'USD': {
        'symbol': '$',
        'name': 'Доллар США',
        'exchange_rate': 0.026  # Примерный курс 1 UAH = 0.026 USD
    },
    'RUB': {
        'symbol': '₽',
        'name': 'Российский рубль',
        'exchange_rate': 2.4  # Примерный курс 1 UAH = 2.4 RUB
    },
    'EUR': {
        'symbol': '€',
        'name': 'Евро',
        'exchange_rate': 0.024  # Примерный курс 1 UAH = 0.024 EUR
    }
}

def get_credit_package_by_type(package_type: str) -> dict:
    """Получение пакета кредитов по типу"""
    return CREDIT_PACKAGES.get(package_type, {})

def get_generation_cost(model: str, format_type: str = None, video_quality: str = None, video_duration: str = None) -> int:
    """Получение стоимости генерации"""
    # Проверяем, это видео Bytedance
    if model == 'Bytedance (Seedream-3)' and video_quality and video_duration:
        video_key = f'Bytedance {video_quality} {video_duration}'
        if video_key in VIDEO_GENERATION_COSTS:
            return VIDEO_GENERATION_COSTS[video_key]
    
    # Для изображений используем базовую стоимость модели
    base_cost = GENERATION_COSTS.get(model, 10)  # По умолчанию 10 кредитов
    format_cost = FORMAT_COSTS.get(format_type, 0)
    return base_cost + format_cost

def format_price(amount: float, currency: str = 'UAH') -> str:
    """Форматирует цену с символом валюты"""
    currency_info = CURRENCY_SETTINGS.get(currency, CURRENCY_SETTINGS['UAH'])
    
    if currency == 'UAH':
        return f"₴{amount:.2f}"
    elif currency == 'USD':
        return f"${amount:.2f}"
    elif currency == 'RUB':
        return f"₽{amount:.2f}"
    elif currency == 'EUR':
        return f"€{amount:.2f}"
    else:
        return f"{amount:.2f} {currency}"

def convert_currency(amount: float, from_currency: str, to_currency: str) -> float:
    """Конвертация валют"""
    if from_currency == to_currency:
        return amount
    
    from_rate = CURRENCY_SETTINGS.get(from_currency, {}).get('exchange_rate', 1.0)
    to_rate = CURRENCY_SETTINGS.get(to_currency, {}).get('exchange_rate', 1.0)
    
    if from_rate and to_rate:
        return amount * (to_rate / from_rate)
    
    return amount

def get_available_credit_packages() -> list:
    """Получение всех доступных пакетов кредитов"""
    return list(CREDIT_PACKAGES.values())

def calculate_discount(original_price: float, discounted_price: float) -> int:
    """Расчет процента скидки"""
    if original_price <= 0:
        return 0
    
    discount_percent = ((original_price - discounted_price) / original_price) * 100
    return int(discount_percent)

# Добавляем скидки к пакетам кредитов
for package_type, package in CREDIT_PACKAGES.items():
    if package_type != 'small':
        # Рассчитываем скидку относительно базовой цены
        base_price = CREDIT_PACKAGES['small']['price_per_credit'] * package['credits']
        package['original_price'] = base_price
        package['discount_percent'] = calculate_discount(base_price, package['price'])
        package['savings'] = base_price - package['price']
    else:
        package['original_price'] = package['price']
        package['discount_percent'] = 0
        package['savings'] = 0
