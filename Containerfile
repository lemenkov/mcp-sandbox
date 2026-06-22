# SPDX-FileCopyrightText: 2026 Peter Lemenkov <lemenkov@gmail.com>
# SPDX-License-Identifier: Apache-2.0

FROM registry.fedoraproject.org/fedora:latest

RUN dnf install -y \
    # R and common packages
    R \
    R-ggplot2 \
    R-dplyr \
    R-tidyr \
    R-jsonlite \
    # GMT - Generic Mapping Tools
    GMT \
    gmt-common \
    # Python scientific stack
    python3 \
    python3-numpy \
    python3-matplotlib \
    python3-scipy \
    python3-pandas \
    python3-sympy \
    python3-scikit-learn \
    # LaTeX
    texlive \
    texlive-latex \
    texlive-collection-latexrecommended \
    # Octave
    octave \
    # Gnuplot
    gnuplot \
    # Julia
    julia \
    # General utilities
    bash \
    coreutils \
    findutils \
    && dnf clean all

# Create sandbox working directories
RUN mkdir -p /sandbox/input /sandbox/output

WORKDIR /sandbox
