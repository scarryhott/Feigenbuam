"""
Skill: load_config_once
Ensure a configuration file is loaded only once using a global flag to prevent redundant loading operations.
"""

def load_config_once(config_file_path: str, loaded_flag: str) -> None:
    """
    Load a configuration file once by checking a global flag.

    :param config_file_path: Path to the configuration file.
    :param loaded_flag: Global flag variable name to track if loading has occurred.
    """
    global_vars = globals()

    if global_vars.get(loaded_flag, False):
        return
    global_vars[loaded_flag] = True

    if not os.path.isfile(config_file_path):
        return

    try:
        with open(config_file_path, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, val = map(str.strip, line.split('=', 1))
                if key and val and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass