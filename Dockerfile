FROM condaforge/mambaforge:latest

RUN apt-get update -y && apt-get install build-essential g++ gcc gcc-arm-linux-gnueabi -y

RUN mkdir /ti4-tg-bot
COPY . /ti4-tg-bot

# todo - mamba env create, set default, etc
WORKDIR /ti4-tg-bot
RUN mamba env create --name ti4-bot

RUN echo "source activate ti4-bot" > ~/.bashrc

# Make RUN commands use `bash --login`:
SHELL ["conda", "run", "--no-capture-output", "-n", "ti4-bot", "/bin/bash", "-c"]

ENTRYPOINT ["conda", "run", "--no-capture-output", "-n", "ti4-bot", "ti4tg"]
