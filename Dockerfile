# Python version can be changed, e.g.
# FROM python:3.8
# FROM docker.io/fnndsc/conda:python3.10.2-cuda11.6.0
FROM docker.io/fnndsc/conda:python3.10.6

LABEL org.opencontainers.image.authors="FNNDSC <dev@babyMRI.org>" \
      org.opencontainers.image.title="Cortical Thickness" \
      org.opencontainers.image.description="A ChRIS plugin wrapper for cortical_thickness and some distortion metrics"

WORKDIR /usr/local/src/pl-cortical_thickness

# install numpy using conda for cross-platform support
RUN conda install -c conda-forge numpy=1.23.3
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
ARG extras_require=none
RUN pip install ".[${extras_require}]"

CMD ["surf_results", "--help"]
