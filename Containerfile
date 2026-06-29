# SPDX-FileCopyrightText: 2026 Peter Lemenkov <lemenkov@gmail.com>
# SPDX-License-Identifier: Apache-2.0

FROM registry.fedoraproject.org/fedora:latest

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
    python3-geopandas \
    python3-matplotlib \
    python3-numpy \
    python3-pandas \
    python3-pyproj \
    python3-rasterio \
    python3-scikit-learn \
    python3-scipy \
    python3-sympy \
    # LaTeX
    texlive \
    texlive-collection-latexrecommended \
    texlive-latex \
    # General utilities
    bash \
    coreutils \
    findutils \
    && dnf clean all

RUN python3 -m pip install --no-cache-dir obspy

# Create sandbox working directories
RUN mkdir -p /sandbox/input /sandbox/output

WORKDIR /sandbox
