FROM colmap/colmap:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY scripts/ /workspace/scripts/
RUN chmod +x /workspace/scripts/*.sh
ENV PATH="/workspace/scripts:${PATH}"

CMD ["/bin/bash"]
