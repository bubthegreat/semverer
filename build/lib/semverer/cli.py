import typer

from semverer.main import ASTVersionInspector

app = typer.Typer()


@app.command()
def inspect(package_path: str):
    """Runs the AST version inspector on a package."""
    inspector = ASTVersionInspector(package_path)
    inspector.run()

if __name__ == "__main__":
    app()
