from datasets import load_dataset

base = "https://huggingface.co/datasets/michaelozon/candidate-matching-synthetic/resolve/main/"


def load_file(path):
    return load_dataset(
        "parquet",
        data_files=base + path,
        split="train",
    )


resumes = load_file("data/resumes-00000-of-00001.parquet")
jobs = load_file("jobs/train-00000-of-00001.parquet")
matches = load_file("matches/train-00000-of-00001.parquet")

for name, records in [
    ("resumes", resumes),
    ("jobs", jobs),
    ("matches", matches),
]:
    print(name, len(records), records.column_names)
    print(records[0])
