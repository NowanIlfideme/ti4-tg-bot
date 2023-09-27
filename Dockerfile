FROM condaforge/mambaforge:latest

# sudo apt install cmake clang binutils-dev

RUN mkdir /ti4-tg-bot
COPY . /ti4-tg-bot

# todo - mamba env create, set default, etc
WORKDIR /ti4-tg-bot
RUN mamba env create --name ti4-bot

RUN echo "source activate ti4-bot" > ~/.bashrc

# Make RUN commands use `bash --login`:
SHELL ["conda", "run", "--no-capture-output", "-n", "ti4-bot", "/bin/bash", "-c"]

ENTRYPOINT ["conda", "run", "--no-capture-output", "-n", "ti4-bot", "ti4tg"]
