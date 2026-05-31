from django.apps import AppConfig


class BackendConfig(AppConfig):
    name = 'backend'

    def ready(self):
        from .services.prediction_service import MatchPredictionService
        MatchPredictionService.load_model()
