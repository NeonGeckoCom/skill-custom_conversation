import setuptools


with open("README.md", "r") as f:
    long_description = f.read()

with open("script_parser/version.py", "r") as v:
    for line in v.readlines():
        if line.startswith("__version__"):
            if '"' in line:
                version = line.split('"')[1]
            else:
                version = line.split("'")[1]

setuptools.setup(
    name="neon-script-parser",
    version=version,
    author="NeonDaniel",
    author_email="daniel@neon.ai",
    description="The Neon AI Script Parser",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/neongeckocom/neon-script-parser",
    packages=["script_parser"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: Apache License 2.0",
        "Operating System :: OS Independent"
    ],
    python_requires='>=3.6'
    )
