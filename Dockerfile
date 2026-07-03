FROM colmap/colmap:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# numpy/pycolmap read the sparse model; trimesh is only needed for the optional .glb output.
RUN pip install --no-cache-dir --break-system-packages numpy pycolmap trimesh

WORKDIR /workspace

COPY scripts/ /workspace/scripts/
RUN chmod +x /workspace/scripts/*.sh /workspace/scripts/*.py
ENV PATH="/workspace/scripts:${PATH}"

CMD ["/bin/bash"]
