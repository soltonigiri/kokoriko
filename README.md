# KOKORIKO — 孤狐狸固

English · [日本語](README.ja.md)

An unofficial engine for playing and analyzing Gungi from *HUNTER×HUNTER*. It implements the commercial game's advanced rules, with C++ search and Python tools for self-play and evaluation model training.

## Run

Requires Linux, a C++20 compiler, Ninja, and [uv](https://docs.astral.sh/uv/).

```bash
./scripts/bootstrap.sh
./scripts/kokoriko.sh
```

An evaluation model is included. Send one JSON request per line on standard input.

```json
{"cmd":"new"}
{"cmd":"legal"}
{"cmd":"search","ms":1000}
```

## Development

See the [development guide](docs/DEVELOPMENT.md) for building, testing, and training, and the [protocol](docs/PROTOCOL.md) for CLI commands.

[Rules](RULES.md) · [Match testing](docs/ARENA.md) · [Evaluation models](docs/MODELS.md) · [Sources](docs/SOURCES.md)

## License

Code, documentation, and the bundled model are available under the [MIT License](LICENSE). Names and rights associated with the original work and official product belong to their respective owners.
