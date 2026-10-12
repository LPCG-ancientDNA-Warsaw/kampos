# Kampos
#### Documentation and tool still on development.

This is the repository for Kampos* (*temporary name), the tool we are building to manage our samples database. This is still a big work in progress, so it is not ready for use. Moreover, collaborators are free to partecipate to the project by forking this repository, but please refrain from changing the core logic of this tool.

### Dependencies
I have yet to prepare a file called "requirements.txt" (It will be the next thing I will do) but you have to make sure to install the dependencies required by Kampos prior to running it. Please check the file <code>pyproject.toml</code> and, at least for now, manually install the dependencies.

### Connecting to our database

At the moment, the <code>config.json</code> file contains all the info required to connect to the database used by LPCG: the idea is to make this tool as general as possible, so in the future the tool will only come with an empty .json file (and a default_config.json one) that will need to be configured and initialized by the user.

For the members of our laboratory, the PostgreSQL database provided by our IT department is reachable only through anthill 3.0, and, on top of that, you need an additional database account (only your anthill 3.0 account is not enough). Once you obtain the account from the IT department, go on the Terminal and open a bridge connection between your local computer - through anthill 3.0 - to the PostgreSQL database by running:

```{bash}
ssh -L 5432:dbengine003.cent.uw.edu.pl:22103 <your anthill 3.0 username>@pier23.cent1.uw.edu.pl
```

This command will request you to provide your passowrd. Once done, you will have successfully created a bridge between your computer and the database. Now, you need to keep this bridge running: to avoid anthill 3.0 kicking you out for inactivity, type and execute <code>top</code>.

On another terminal window, move to the directory of kampos, and run its web view by executing:

```{bash}
streamlit run .\kampos\app_streamlit.py 
```

This will display a link that you can press on to open your browser and view the web version.

### We are voting to change the name of the tool!

On another note, we are taking suggestions to change the name. You can edit this markdown file to add your ideas (please provide an explanation about it) and/or vote on the others'. There is no judgement involved, so give your best shot!

- KAMPOS: The idea comes from the fact that this tool will help the user generate the metadata files required for the submission on public repositories. One of them is Poseidon. Poseidon's sacred animal is the horse, but as out laboratory works on mammals I didn't want this tool to look like it was referencing the research of only one member: so I though about using the Seahorse as symbol. The scientific name of the seahorse is Hippocampus, which is formed by the words Hippos (horse) and Kampos (sea monster). And there is where Kampos comes from.
- Lustro: easy-to-pronounce word that means "5 years" (in latin), referencing to the 5 rotating backups, and "mirror" (in polish), referencing the fact that the tool gives a nice, clear, user view of the database.
- Arkìo: archeio is the greek word for archive. It is pronounced as arhìo (almost like the polish ch sound) and with the accent on the i. This sound, though, could be hard to guess from the spelling and pronounced by romance-languages speaking people (yes, I am talking specifically about italian) so I would go with a slightly different spelling and pronunciation;
- Testa: italian word for head, which references the fact that this tool helps us keep all important info in our mind.
- Charybdis: mythological sea monster close to Sicily;
- Nawia: the underworld in slavic mythology.
  
