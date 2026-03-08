from __future__ import annotations

from pathlib import Path

import typer

from taxonomy import get_taxonomy, get_terms_for_branch

app = typer.Typer(help="Outils CLI pour Artiste Coloriage")


@app.command()
def list_themes() -> None:
    """
    Lister les principaux thèmes (racine de la taxonomie universelle).
    """
    taxonomy = get_taxonomy()
    for vocab in taxonomy.vocabularies:
        typer.echo(f"Vocabulaire: {vocab.id}")
        for term in vocab.terms:
            typer.echo(f"- {term.id}: {term.name_fr} / {term.name_en}")


@app.command()
def show_branch(term_id: str) -> None:
    """
    Afficher une branche de la taxonomie (terme + descendants).
    """
    taxonomy = get_taxonomy()
    terms = get_terms_for_branch(taxonomy, term_id=term_id)
    if not terms:
        typer.echo(f"Aucun terme trouvé pour id='{term_id}'")
        raise typer.Exit(code=1)
    for term in terms:
        depth = 0
        current_parent = term.parent_id
        while current_parent:
            parent = taxonomy.find_term(current_parent)
            if parent is None:
                break
            depth += 1
            current_parent = parent.parent_id
        indent = "  " * depth
        typer.echo(f"{indent}- {term.id}: {term.name_fr} / {term.name_en}")


@app.command()
def input_theme() -> None:
    """
    Saisie interactive d'un thème libre, avec rappel de quelques exemples.
    """
    taxonomy = get_taxonomy()
    typer.echo("Quelques thèmes existants dans la taxonomie :")
    for vocab in taxonomy.vocabularies:
        for term in vocab.terms:
            typer.echo(f"- {term.name_fr} / {term.name_en} (id={term.id})")
    theme = typer.prompt("Saisis un thème général (texte libre)")
    typer.echo(f"Thème saisi: {theme}")
    # Le rattachement automatique à un terme précis sera traité dans les phases suivantes.


if __name__ == "__main__":
    app()

