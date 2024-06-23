from pathlib import Path
import json
from jsonschema import validate as json_validate
import logging
__author__ = "Robert Detlof"

log = logging.getLogger("RelayConfig")

CONFIG_SCHEMA = {
    "type": "object",
    "required": [
        "labels",
        "buttons"
    ],
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },
        "buttons": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["action", "label", "targets"],
                "properties": {
                    "action": {
                        "enum": ["activate", "deactivate", "toggle", "pulse"]
                    },
                    "label": {"type": "string"},
                    "targets": {
                        "type": "array",
                        "items": {
                            "type": "integer"
                        }
                    },
                    "duration": {
                        "type": "integer"
                    }
                }
            }
        }
    }   
}

"""
DEFAULT_CONFIG = {
    "labels" : [],
    "buttons": [
        {
            "action": "activate",
            "label": "All On",
            "targets" : [1, 2, 3, 4, 5, 6, 7, 8]
        },
        {
            "action": "deactivate",
            "label": "All Off",
            "targets" : [1, 2, 3, 4, 5, 6, 7, 8]
        }
    ]
}
"""


DEFAULT_CONFIG = {
    "labels" : [],
    "buttons": [
        {
            "action": "activate",
            "label": "All On",
            "targets" : [1, 2, 3, 4, 5, 6, 7, 8]
        },
        {
            "action": "deactivate",
            "label": "All Off",
            "targets" : [1, 2, 3, 4, 5, 6, 7, 8]
        },
        {
            "action": "activate",
            "label": "1-5 On",
            "targets" : [1, 2, 3, 4, 5]
        },
        {
            "action": "pulse",
            "label": "Pulse 6,7,8",
            "targets" : [6, 7, 8],
            "duration": 500
        }
    ]
}

"""
DEFAULT_CONFIG = {
    "labels" : [],
    "buttons": []
}
"""

CONFIG_NAME = "relay_config.json"

def file_exists(config_path):
    return Path.is_file(config_path)

def read_config_file(config_path):
    result = ""
    with open(config_path, mode="r") as f:
        result = f.read()
    return result

def write_config_file(config_path, text_content):
    with open(config_path, mode="w") as f:
        f.write(text_content)

def parse_json(text_content):
    return json.loads(text_content)

def dict_to_json(dict_content, indent=2):
    return json.dumps(dict_content, indent=indent)

def load_config(allow_write=True):
    path_cwd = Path.cwd()
    path_config = path_cwd.joinpath(CONFIG_NAME)

    print(path_cwd)
    print(path_config)

    current_config = DEFAULT_CONFIG

    if not file_exists(path_config):

        log.warning("Config file does not exist. Using default config.")
        
        if allow_write:
            log.debug("Attempting to write default config to file....")
            config_text = dict_to_json(current_config)
            write_config_file(config_path=path_config, text_content=config_text)

    else:
        log.debug("Found config file. Reading...")
        config_file_text = read_config_file(config_path=path_config)
        config_file_json = parse_json(text_content=config_file_text)
        current_config = config_file_json

    log.debug("Validating config...")

    json_validate(current_config, schema=CONFIG_SCHEMA) # throws jsonschema.exceptions.ValidationError

    log.debug("Final config:")
    log.debug(json.dumps(current_config, indent=2))

    return current_config

try:
    load_config()
except Exception as e:
    log.error(type(e).__name__)
    log.error(e)