from setuptools import setup, find_packages

setup(
    name="app",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "pydantic",
        "python-jose",
        "passlib",
        "python-dotenv",
        "requests",
        "schedule",
        "pytz",
        "boto3",
        "jinja2",
        "python-multipart",
        "email-validator",
    ],
)
