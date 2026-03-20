# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## High-Level Code Architecture

This project is a Dash web application designed for ZAR/USD exchange rate forecasting and analysis.

-   **Application Entry Point**: `app.py` initializes the Dash application, handles theme switching, and manages authentication redirects. It uses `dash.page_container` for multi-page routing.
-   **Multi-Page Structure**: The `pages/` directory contains the individual Dash pages:
    -   `pages/login.py`: Provides a landing page and handles user login functionality, authenticating against a Supabase `users` table.
    -   `pages/registration.py`: Manages new user registration, adding credentials to the Supabase `users` table.
    -   `pages/dashboard.py`: The main authenticated area, featuring "Data Explorer" and "Model" tabs for data visualization and macroeconomic forecasting.
-   **Core Logic (`logic/`)**: This directory encapsulates the business logic:
    -   `logic/supabase_client.py`: Manages the connection and interactions with the Supabase database.
    -   `logic/data_fetcher.py`: Responsible for fetching macroeconomic data from external APIs (FRED, World Bank) and local sources, processing it, and persisting it to Supabase.
    -   `logic/model.py`: Contains the machine learning model (ElasticNet/Lasso) for predicting the next month's ZAR/USD exchange rate. It loads a pre-trained model for predictions.
-   **Frontend Assets (`assets/`)**: Contains static files such as images (e.g., logos) and client-side JavaScript (`interactions.js`), along with global CSS (`style.css`).
-   **Data Storage**: Supabase is used as the primary data backend for user authentication and storing processed financial data.
-   **Environment Configuration**: Sensitive API keys and database credentials are managed via environment variables loaded from a `.env` file using `python-dotenv`.

## Commonly Used Commands

-   **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
-   **Run the Application (Development Mode)**:
    ```bash
    python app.py
    ```
    This command starts the Dash application in debug mode, which is suitable for local development.
-   **Run the Application (Production Mode)**:
    ```bash
    gunicorn app:server
    ```
    This command uses Gunicorn to serve the application, as defined in the `Procfile`, suitable for production deployments.

**Note on Testing and Linting**:
There are no explicit test files or a dedicated testing framework configured in this repository. Similarly, no specific linting configurations (e.g., `.pylintrc`, `pyproject.toml`) were found.
