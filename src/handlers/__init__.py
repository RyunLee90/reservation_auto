from . import agoda, ctrip, hikari, yeogi, yanolja

HANDLERS = {
    "히카리글로벌": hikari,
    "아고다": agoda,
    "씨트립": ctrip,
    "여기어때": yeogi,
    "야놀자": yanolja,
}


def get_handler(account_name: str):
    return HANDLERS.get(account_name)