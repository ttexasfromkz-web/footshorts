"""Output language for generated video graphics and publishing copy."""

LANGUAGES={'Қазақша':'kk','Русский':'ru','English':'en'}


def normalize(value='kk'):
    value=LANGUAGES.get(value,value)
    if value not in LANGUAGES.values():
        raise ValueError('Материал тілі: Қазақша, Русский немесе English таңдаңыз.')
    return value


def label(value='kk'):
    code=normalize(value)
    return next(name for name,key in LANGUAGES.items() if key==code)


TEXT={
    'kk':dict(highlights='Матчтың үздік сәттері',football_highlights='Футболдың үздік сәттері',
        goal='ГООЛ!',replay='ҚАЙТАЛАУ',final='СОҢҒЫ ЕСЕП',unknown_final='ЕСЕП АНЫҚТАЛМАДЫ',
        team_a='КОМАНДА 1',team_b='КОМАНДА 2',score='Есеп',unknown='анықталмады',
        video_title='ВИДЕО АТАУЫ',description='СИПАТТАМА (хештегтерімен бірге)',tags='ТЕГТЕР',
        watch='Матчтың іріктелген қызықты сәттерін тамашала!',
        comment='Қай сәт саған көбірек ұнады? Пікірге жаз! 👇',subscribe='Футбол үзінділері үшін арнаға жазыл!',
        music='Фондық музыка',source='Бастапқы видео',review='ЖАРИЯЛАУ АЛДЫНДА ТЕКСЕРУ',
        unknown_teams='Командалар атауы автоматты анықталмады. Матч атауын түзетіңіз.',
        unknown_score='Есеп оқылмады. 0:0 деп болжанған жоқ. Есепті енгізіп қайта жасаңыз.',
        logo_sources='ЛОГОТИПТЕРДІҢ ДЕРЕККӨЗДЕРІ',
        hashtags=['#Футбол','#ҮздікСәттер','#Голдар','#Shorts'],
        keywords=['футбол','матчтың үздік сәттері','голдар','футбол шортс','shorts']),
    'ru':dict(highlights='Лучшие моменты матча',football_highlights='Лучшие моменты футбола',
        goal='ГОООЛ!',replay='ПОВТОР',final='ИТОГОВЫЙ СЧЁТ',unknown_final='СЧЁТ НЕ ОПРЕДЕЛЁН',
        team_a='КОМАНДА 1',team_b='КОМАНДА 2',score='Счёт',unknown='не определён',
        video_title='НАЗВАНИЕ ВИДЕО',description='ОПИСАНИЕ (с хештегами)',tags='ТЕГИ',
        watch='Смотри подборку ярких моментов матча!',
        comment='Какой момент понравился больше всего? Напиши в комментариях! 👇',subscribe='Подписывайся на канал с футбольными моментами!',
        music='Фоновая музыка',source='Исходное видео',review='ПРОВЕРЬТЕ ПЕРЕД ПУБЛИКАЦИЕЙ',
        unknown_teams='Названия команд не распознаны. Исправьте название матча.',
        unknown_score='Счёт не распознан. Значение 0:0 не подставлялось. Введите счёт и создайте видео заново.',
        logo_sources='ИСТОЧНИКИ ЛОГОТИПОВ',
        hashtags=['#рекомендации','#рекомендация','#Футбол','#ОбзорМатча','#Голы','#Shorts'],
        keywords=['футбол','лучшие моменты матча','обзор матча','голы','футбол шортс','shorts']),
    'en':dict(highlights='Match highlights',football_highlights='Football highlights',
        goal='GOAL!',replay='REPLAY',final='FINAL SCORE',unknown_final='SCORE UNAVAILABLE',
        team_a='TEAM 1',team_b='TEAM 2',score='Score',unknown='unavailable',
        video_title='VIDEO TITLE',description='DESCRIPTION (with hashtags)',tags='TAGS',
        watch='Watch the selected highlights from the match!',
        comment='Which moment was your favourite? Tell us in the comments! 👇',subscribe='Subscribe for more football highlights!',
        music='Background music',source='Original video',review='CHECK BEFORE PUBLISHING',
        unknown_teams='Team names were not recognised. Correct the match title.',
        unknown_score='The score could not be read. It was not assumed to be 0:0. Enter the score and recreate the video.',
        logo_sources='LOGO SOURCES',
        hashtags=['#Football','#Highlights','#Goals','#Shorts'],
        keywords=['football','match highlights','football highlights','football shorts','goals','shorts']),
}


def strings(language='kk'):
    return TEXT[normalize(language)]
