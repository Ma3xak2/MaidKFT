import yaml
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.yaml")
ACTIONS_PATH = os.path.join(BASE_DIR, "config", "actions.yaml")


def load_yaml(filename):
    with open(filename, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)


def load_actions_normalized():
    raw = load_yaml(ACTIONS_PATH)
    # Нормализуем ключи в нижний регистр
    return {key.strip().lower(): template for key, template in raw.items()}


def load_config():
    config = load_yaml(CONFIG_PATH)
    config["ACTIONS"] = load_actions_normalized()
    config["_paths"] = {"actions": ACTIONS_PATH}
    return config


def save_actions(actions: dict):
    # Записываем оригинальный YAML (без нормализации ключей, 
    # но сохраняем всё в нижнем регистре для единообразия)
    save_yaml(ACTIONS_PATH, {k.lower(): v for k, v in actions.items()})
