from .auth import auth_bp
from .students import students_bp
from .companies import companies_bp
from .universities import universities_bp
from .jobs import jobs_bp
from .matching import matching_bp
from .analytics import analytics_bp
from .admin import admin_bp, platform_bp
from .internships import internships_bp
from .certificates import certificates_bp
from .messages import messages_bp
from .evaluation import evaluation_bp


def register_routes(app):
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(students_bp, url_prefix="/api/students")
    app.register_blueprint(internships_bp, url_prefix="/api/students")
    app.register_blueprint(companies_bp, url_prefix="/api/companies")
    app.register_blueprint(universities_bp, url_prefix="/api/universities")
    app.register_blueprint(jobs_bp, url_prefix="/api/jobs")
    app.register_blueprint(matching_bp, url_prefix="/api/matching")
    app.register_blueprint(analytics_bp, url_prefix="/api/analytics")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(platform_bp, url_prefix="/api/platform")
    app.register_blueprint(certificates_bp, url_prefix="/api/certificates")
    app.register_blueprint(messages_bp, url_prefix="/api/messages")
    app.register_blueprint(evaluation_bp, url_prefix="/api/evaluation")
