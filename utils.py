import os


REQUIRED_AUTH_KEYS = [
    'url',
    'authorization',
    'cookie',
    'referer',
    'user_agent',
    'oai_client_version',
    'oai_device_id',
    'oai_language',
]


def prompt_yes_no(message: str, default: bool = True) -> bool:
    """Prompt the user with a yes/no question.

    Args:
        message: The question to display to the user.
        default: The return value if the user just hits enter.

    Returns:
        ``True`` for yes and ``False`` for no.
    """

    prompt = f"{message} [{'Y/n' if default else 'y/N'}]: "
    while True:
        choice = input(prompt).strip().lower()
        if not choice:
            return default
        if choice in ('y', 'yes'):
            return True
        if choice in ('n', 'no'):
            return False
        print("Please enter 'y' or 'n'.")


def load_auth_config(path: str = 'auth.txt') -> dict:
    """Load key=value lines from auth.txt into a dict.
    Ignores lines without '=' and whitespace-only lines.
    """
    config = {}
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or '=' not in line:
                continue
            key, value = line.split('=', 1)
            config[key.strip()] = value.strip()
    return config


def prompt_and_write_auth(path: str = 'auth.txt') -> dict:
    print('\nAuth file not found or invalid. Let\'s create it.\n')
    print('Instructions: In your browser, open Developer Tools → Network,')
    print("find a request to 'image_gen', and copy these exact header values.\n")

    cfg = {}
    for key in REQUIRED_AUTH_KEYS:
        while True:
            val = input(f"{key} = ").strip()
            if val:
                cfg[key] = val
                break
            else:
                print('This field is required. Please enter a value.')

    with open(path, 'w', encoding='utf-8') as f:
        for k in REQUIRED_AUTH_KEYS:
            f.write(f"{k}={cfg[k]}\n")

    print(f"\nSaved credentials to {path}.\n")
    return cfg


def ensure_auth_config(path: str = 'auth.txt') -> dict:
    try:
        cfg = load_auth_config(path)
    except FileNotFoundError:
        if prompt_yes_no('auth.txt not found. Create it now?'):
            cfg = prompt_and_write_auth(path)
        else:
            raise

    # Basic validation
    missing = [k for k in REQUIRED_AUTH_KEYS if not cfg.get(k)]
    if missing:
        print(f"auth.txt is missing keys: {', '.join(missing)}")
        if prompt_yes_no('Re-enter credentials now?'):
            cfg = prompt_and_write_auth(path)
        else:
            raise ValueError(f"Missing required keys: {missing}")

    return cfg

