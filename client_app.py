import blockchain_client as client

def main():
   
    args = client.arg_parse()
    client.run_app(client.setup(args))




if __name__ == "__main__":
    main()