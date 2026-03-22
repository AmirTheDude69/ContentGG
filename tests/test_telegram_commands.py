from app.bot.commands import extract_reel_url, parse_bot_command


def test_parse_bot_command_with_argument() -> None:
    command = parse_bot_command('/add https://www.instagram.com/reel/ABC123/')
    assert command.name == '/add'
    assert command.argument == 'https://www.instagram.com/reel/ABC123/'


def test_extract_reel_url() -> None:
    text = 'check this https://www.instagram.com/reel/ABC123/?utm_source=ig'
    assert extract_reel_url(text) == 'https://www.instagram.com/reel/ABC123/'
