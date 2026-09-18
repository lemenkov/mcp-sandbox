# SPDX-FileCopyrightText: 2026 Peter Lemenkov <lemenkov@gmail.com>
# SPDX-License-Identifier: Apache-2.0

FROM registry.fedoraproject.org/fedora:44

RUN dnf install -y \
    # R and common packages
    R \
    R-dplyr \
    R-ggplot2 \
    R-jsonlite \
    R-tidyr \
    # GMT - Generic Mapping Tools
    GMT \
    gmt-common \
    # Gnuplot
    gnuplot \
    # GRASS GIS
    grass \
    # Julia
    julia \
    # Octave
    octave \
    # Python scientific stack
    python3 \
    python3-cartopy \
    python3-geopandas \
    python3-h5py \
    python3-matplotlib \
    python3-netcdf4 \
    python3-numpy \
    python3-obspy \
    python3-pandas \
    python3-pygmt \
    python3-pyproj \
    python3-pyyaml \
    python3-rasterio \
    python3-scikit-learn \
    python3-scipy \
    python3-sympy \
    # Python development / QA
    python3-hypothesis \
    python3-mypy \
    python3-pytest \
    ruff \
    # Shell tooling (the bash runtime has no linter)
    ShellCheck \
    shfmt \
    # LaTeX
    texlive \
    texlive-collection-latexrecommended \
    texlive-latex \
    # General utilities
    bash \
    coreutils \
    findutils \
    jq \
    git-core \
    patch \
    && dnf clean all

# Create sandbox working directories
RUN mkdir -p /sandbox/input /sandbox/output

WORKDIR /sandbox
