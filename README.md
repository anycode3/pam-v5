# PAM - Layout Iteration Automation Engine

PAM (Layout Iteration Automation Engine) is a tool for automating layout iterations in RF chip design.

## Features

- KiCad netlist parsing
- Electrical to geometry parameter mapping
- KLayout PCell generation (GDS output)
- DRC design rule check
- LVS layout vs schematic verification
- StretchRouter device stretching
- Snapshot manager for iteration state

## Installation

```bash
pip install -e ".[dev]"
```

## Quick Start

```bash
# Initialize layout from parameters
pam init --netlist circuit.net --params params.json --output layout.gds

# Run iterative optimization
pam run --gds layout.gds --netlist circuit.net --target new_params.json --output updated.gds
```

## Documentation

See [docs/USER_GUIDE.md](docs/USER_GUIDE.md) for detailed usage instructions.
