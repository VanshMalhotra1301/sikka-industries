import os
from app import create_app

# Determine environment from ENV variable, default to development
env = os.environ.get('FLASK_ENV', 'development')
app = create_app(env)

if __name__ == '__main__':
    is_production = env == 'production'
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=not is_production
    )
