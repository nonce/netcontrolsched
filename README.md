# NetControlSched (NCS)
#### v0.1b
##### *by: kg6o*

------------------------
This module is designed to be run at regular intervals in order to email out
recurring meeting reminders where meeting responsibilities
rotate with each meeting.

It's free, so sheetsu is incorporated as a data source.


### Install 

    `pip install -r requirements.txt`
    
### Use

    `python email.py`
     
Note that the command line arguments (see 'help', below)
takes precedence over environment variables,  which takes precedence 
over .yml configs. 
    
### Help

    `python email.py --help`
    
### TODO

- make this a class, to fully modularise the *_render methods,` so that new scripts
will implement standard methods for new uses.

- make a data source interface, not just use Sheetsu.

- remove any logic from 'main'

- make this executable in it's own venv with a good install...

- breed an install with CFN for lambda-based deploy and CWE scheduled runs

- if there are issues or warnings, there should be an email automatically sent.
 This means the config needs to have the notification/report email address
 
-   
