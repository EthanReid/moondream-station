import logging
import re
from config import Config

class Parser:
    @staticmethod
    def parse_updates(output):
        components = {}
        lines = [line.strip() for line in output.replace('\r', '\n').split('\n') 
                if line.strip() and not line.strip().startswith('Checking for') and not line.strip().startswith('admin')]
        
        for line in lines:
            if ':' in line and (Config.STATUS_INDICATORS['up_to_date'] in line or 
                               Config.STATUS_INDICATORS['update_available'] in line):
                parts = line.split(':', 1)
                if len(parts) >= 2:
                    component = parts[0].strip()
                    status_part = parts[1].strip()
                    
                    for name in Config.COMPONENT_NAMES:
                        if name.lower() in component.lower():
                            component = name
                            break
                    
                    if Config.STATUS_INDICATORS['update_available'] in status_part:
                        components[component] = Config.STATUS_INDICATORS['update_available']
                    elif Config.STATUS_INDICATORS['up_to_date'] in status_part:
                        components[component] = Config.STATUS_INDICATORS['up_to_date']
        
        logging.debug(f"Parsed components: {components}")
        return components
    
    @staticmethod
    def parse_versions_from_check_updates(output):
        versions = {}
        for line in output.split('\n'):
            line = line.strip()
            for component, pattern in Config.VERSION_Config['check_updates'].items():
                match = re.search(pattern, line)
                if match:
                    if component == 'model':
                        versions[component] = match.group(1).strip()
                    else:
                        versions[component] = match.group(1)
                    break
        
        logging.debug(f"Parsed versions from check-updates: {versions}")
        return versions
    
    @staticmethod
    def parse_versions_from_config(output):
        versions = {}
        for line in output.split('\n'):
            line = line.strip()
            for component, pattern in Config.VERSION_Config['get_config'].items():
                match = re.search(pattern, line)
                if match:
                    versions[component] = match.group(1).strip()
                    break
        
        logging.debug(f"Parsed versions from get-config: {versions}")
        return versions
    
    @staticmethod
    def parse_models(output):
        models = {}
        current_model = None
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith(Config.MODEL_FIELDS['name']):
                current_model = line[len(Config.MODEL_FIELDS['name']):].strip()
                models[current_model] = {}
            elif current_model and line.startswith(Config.MODEL_FIELDS['release_date']):
                models[current_model]['release_date'] = line[len(Config.MODEL_FIELDS['release_date']):].strip()
            elif current_model and line.startswith(Config.MODEL_FIELDS['size']):
                models[current_model]['model_size'] = line[len(Config.MODEL_FIELDS['size']):].strip()
            elif current_model and line.startswith(Config.MODEL_FIELDS['notes']):
                models[current_model]['notes'] = line[len(Config.MODEL_FIELDS['notes']):].strip()
        logging.debug(f"Parsed models: {list(models.keys())}")
        return models
    
    @staticmethod
    def parse_config(output):
        config = {}
        for line in output.split('\n'):
            line = line.strip()
            if ':' in line and not line.startswith('Getting server configuration'):
                key, value = line.split(':', 1)
                config[key.strip()] = value.strip()
        logging.debug(f"Parsed config: {config}")
        return config