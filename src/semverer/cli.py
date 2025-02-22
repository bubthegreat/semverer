import typer

from semverer.main import ASTVersionInspector

app = typer.Typer()


@app.command()
def update(package_path: str):
    """Update a package version based on semver inspection of the AST."""
    inspector = ASTVersionInspector(package_path)
    inspector.run()


@app.command()
def check(package_path: str):
    """Show changes that would be applied to a package version based on semver inspection of the AST."""
    inspector = ASTVersionInspector(package_path, dry_run=True)
    inspector.run()


