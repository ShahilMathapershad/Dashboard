from dash import Dash, html, dcc, callback, Output, Input
import dash

app = Dash(__name__)

app.layout = html.Div([
    dcc.Input(id='i', value='test'),
    html.Div(id='o')
])

try:
    @callback(
        Output('o', 'children', allow_duplicate=True),
        Input('i', 'value'),
        prevent_initial_call='initial_duplicate'
    )
    def update(v):
        return v
    print("Callback registration successful with 'initial_duplicate'")
except Exception as e:
    print(f"Error during callback registration: {e}")
