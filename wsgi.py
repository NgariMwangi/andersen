"""Production WSGI entry point."""
import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
application = create_app()

if __name__ == '__main__':
    application.run()
