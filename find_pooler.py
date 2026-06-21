import pg8000.dbapi

regions = [
    "ap-south-1",    # Mumbai
    "us-east-1",     # N. Virginia
    "us-west-1",
    "us-west-2",
    "eu-central-1",
    "ap-southeast-1", # Singapore
    "ap-northeast-1", # Tokyo
    "ap-northeast-2", # Seoul
    "ap-northeast-3", # Osaka
    "ap-southeast-2", # Sydney
    "ca-central-1",   # Canada
    "eu-west-1",      # Ireland
    "eu-west-2",      # London
    "eu-west-3",      # Paris
    "eu-north-1",     # Stockholm
    "sa-east-1",      # Sao Paulo
    "af-south-1"      # Cape Town
]

project_ref = "qzqrcptvmunsenvzwpcc"
password = "MokkshSikka"

success_url = None

for region in regions:
    host = f"aws-0-{region}.pooler.supabase.com"
    user = f"postgres.{project_ref}"
    print(f"Trying {region} ({host})...")
    try:
        conn = pg8000.dbapi.connect(
            host=host,
            user=user,
            password=password,
            database="postgres",
            port=6543,
            timeout=5
        )
        print(f"Success! Region is {region}")
        success_url = f"postgresql://{user}:{password}@{host}:6543/postgres"
        conn.close()
        break
    except Exception as e:
        print(f"Failed {region}: {e}")

if success_url:
    print(f"\nFOUND_URL={success_url}")
else:
    print("\nCould not find the correct region pooler URL.")
