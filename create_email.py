#!/usr/bin/env python
import argparse
import copy
import datetime
import os
import os.path
import pickle
import smtplib
import webbrowser
import yaml

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from os.path import basename

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from jinja2 import Template
import sheetsu

EMAIL_CONFIG = "./email.yml"
SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly']


def get_net_script(net_script_id):
    # from https://developers.google.com/drive/api/v3/quickstart/python
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server()
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('drive', 'v3', credentials=creds)

    # Call the Drive v3 API
    results = service.files().list(
        pageSize=10, fields="nextPageToken, files(id, name)").execute()
    items = results.get('files', [])

    if not items:
        print('No files found.')
    else:
        print('Files:')
        for item in items:
            print(u'{0} ({1})'.format(item['name'], item['id']))


def send_email(server, port, password, sender, to, cc, bcc, subject,
               html, text, attachments):
    toaddrs = to + cc + bcc
    print(toaddrs)
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ",".join(to)
    message["Cc"] = ",".join(cc)
    message.attach(MIMEText(text, "plain"))
    message.attach(MIMEText(html, "html"))

    for file in attachments:
        print('Attaching: {}'.format(file))
        path = os.path.join('.', file)
        with open(path, "rb") as fil:
            part = MIMEApplication(
                fil.read(),
                Name=basename(path)
            )
        # After the file is closed
        part['Content-Disposition'] = 'attachment; filename="%s"' % basename(path)
        message.attach(part)

    with smtplib.SMTP(server, port) as s:
        s.starttls()
        s.login(sender, password)
        s.sendmail(
            sender, toaddrs, message.as_string()
        )
        s.close()


def save_html(html, filename):
    with open(filename, 'w') as fp:
        fp.write(html)


def get_template(file='email.njk'):
    with open(file) as fp:
        return fp.read()


def get_sheetsu_items_secure(api_id, api_key, api_secret):
    client = sheetsu.SheetsuClient(api_id, api_key=api_key,
                                   api_secret=api_secret)
    return client.read()


def get_sheetsu_items(nickname_api_id):
    client = sheetsu.SheetsuClient(nickname_api_id)
    return client.read()


def render_body(sched_items, today, template, warning_threshold, nicknames,
                band_mappings):
    j_template = Template(template)
    today_dt = datetime.date.fromisoformat(today)
    window_dt = today_dt + datetime.timedelta(weeks=8)
    next_nets = {}
    items = []

    # place net list
    for line in sched_items:
        if line['Date']:
            d = datetime.date.fromisoformat(line['Date'])
            if today_dt <= d <= window_dt:
                next_nets[d.isoformat()] = line

    it = sorted(next_nets.keys())

    x = band_mappings
    for i in it:
        o = next_nets[i]
        items.append({x[k]: o[k] for k in o})

    # form words for upcoming week
    upcoming = datetime.date.fromisoformat(items[0]['Date'])
    diff = upcoming - today_dt
    when = 'Today'
    if diff.days > 1:
        when = 'This ' + upcoming.strftime('%A')
    elif diff.days == 1:
        when = 'Tomorrow'

    o = copy.deepcopy(items[0])
    o.pop('Date')
    x_inv = {x[k]: k for k in x}
    nc_list = {x_inv[k]: o[k] for k in o}

    # make cell item tags
    n = 0
    for item in items:
        tags = {}
        n += 1
        for i in item:
            if i == "Date":
                tags[i] = 'date-cell'
            elif item[i] == 'OPEN':
                if n <= warning_threshold:
                    tags[i] = 'warning-cell'
                else:
                    tags[i] = 'open-cell'
            else:
                tags[i] = 'call-cell'
            if n == 1:
                tags[i] += ' first'
        item['tags'] = tags

    whos_up = {}
    for band in nc_list:
        if nc_list[band] not in whos_up:
            whos_up[nc_list[band]] = [band]
        else:
            whos_up[nc_list[band]].append(band)

    open_slot_strings = []
    if 'OPEN' in whos_up:
        bands = whos_up['OPEN']
        for band in bands:
            open_slot_strings.append('We still need a Net Control for the '
                                     'upcoming {} Net!'.format(band))
    print(open_slot_strings)

    whos_up_strings = []
    for who in whos_up:
        if who == 'OPEN':
            continue
        bands = whos_up[who]
        whostring = ''
        if who in nicknames:
            whostring += '{} '.format(nicknames[who])
        whostring += '(<span class="callsign">{}</span>) will be ' \
                     'handling the {}'.format(who, bands.pop())
        if bands:
            while bands:
                if len(bands) == 1:
                    whostring += ', and {} nets.'.format(bands.pop())
                else:
                    whostring += ', {}'.format(bands.pop())
        else:
            whostring += ' net.'
        whos_up_strings.append(whostring)

    return j_template.render(whos_up_strings=whos_up_strings,
                             open_slot_strings=open_slot_strings,
                             when=when,
                             items=items), when, upcoming


def get_config(config_file):
    config = {}
    print("reading {}".format(config_file))
    try:
        with open(config_file, 'r') as ymlfile:
            c = yaml.load(ymlfile)
            config.update(c)
            if 'SUBS' in c:
                for sub in c['SUBS']:
                    config.update(get_config(sub))
            return config
    except Exception as e:
        print("Error with Config {}: {}".format(config_file, e))
        print("Continuing with an empty config.")
        return {}


def main():
    # we want the given args to take precedence over env vars to take precedence
    # over the in-directory config.

    config_file = os.getenv('EMAIL_CONFIG', EMAIL_CONFIG)
    config = get_config(config_file)

    # let's get our subordinate configs, and update the master config
    sub_configs = config.get('SUBS', [])
    for conf in sub_configs:
        print('Reading config "{}"'.format(conf))
        config.update(get_config(conf))

    parser = argparse.ArgumentParser()
    parser.add_argument('--sheetsu-schedule-api-id',
                        help='Sheetsu Schedule API ID',
                        type=str,
                        default=os.environ.get('SHEETSU_SCHEDULE_API_ID',
                                               config.get('SHEETSU_SCHEDULE_API_ID')))
    parser.add_argument('--sheetsu-nickname-api-id',
                        help='API ID for Sheetsu Nickname Lookup',
                        type=str,
                        default=os.environ.get('SHEETSU_NICKNAME_API_ID',
                                               config.get(
                                                   'SHEETSU_NICKNAME_API_ID')))
    parser.add_argument('--sheetsu-api-key',
                        help='sheetsu API KEY',
                        type=str,
                        default=os.environ.get('SHEETSU_API_KEY',
                                               config.get('SHEETSU_API_KEY')))
    parser.add_argument('--sheetsu-api-secret',
                        help='sheetsu API SECRET',
                        type=str,
                        default=os.environ.get('SHEETSU_API_SECRET',
                                               config.get(
                                                   'SHEETSU_API_SECRET')))
    parser.add_argument('--weeks',
                        help='how many upcomming weeks to show in the report',
                        type=int,
                        default=os.environ.get('WEEKS',
                                               config.get('WEEKS')))
    parser.add_argument('--date',
                        help='ISO Format Date (YYYY-MM-DD) Overide',
                        type=str,
                        default=datetime.date.today().isoformat())
    parser.add_argument('--net-day',
                        help='Day of the week for the net',
                        type=str,
                        default=os.environ.get('NET_DAY',
                                               config.get('NET_DAY')))
    parser.add_argument('--template',
                        help='relative file uri of .njk',
                        type=str,
                        default='email.njk')

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument('--print',
                              help='print or email the rendered template',
                              action='store_true')
    output_group.add_argument('--web',
                              help='render email body in the '
                                   'default web browser',
                              action='store_true')

    parser.add_argument('--sender', #can't use 'from', as it's a python reserved word
                        help='Email of message sender',
                        type=str,
                        default=os.environ.get('SENDER',
                                               config.get('SENDER')))
    parser.add_argument('--to',
                        help='Reciver of the email',
                        action='append',
                        type=str,
                        default=os.environ.get('TO',
                                               config.get('TO', [])))
    parser.add_argument('--cc',
                        help='CC Reciver of the email',
                        action='append',
                        type=str,
                        default=os.environ.get('CC',
                                               config.get('CC', [])))
    parser.add_argument('--bcc',
                        help='BCC Receiver of the email',
                        action='append',
                        type=str,
                        default=os.environ.get('BCC',
                                               config.get('BCC', [])))
    parser.add_argument('--attachment',
                        help='relative filename of an attachment to '
                             'include with the email',
                        action='append',
                        type=str,
                        default=os.environ.get('ATTACHMENT',
                                               config.get('ATTACHMENT', [])))
    parser.add_argument('--subject',
                        help='Subject odf the email',
                        type=str,
                        default=os.environ.get('SUBJECT',
                                               config.get('SUBJECT')))
    parser.add_argument('--email-password',
                        help='SMTP Server Sender Password',
                        type=str,
                        default=os.environ.get('EMAIL_PASSWORD',
                                               config.get('EMAIL_PASSWORD')))
    parser.add_argument('--email-server',
                        help='SMTP Server (with tls)',
                        type=str,
                        default=os.environ.get('EMAIL_SERVER',
                                               config.get('EMAIL_SERVER')))
    parser.add_argument('--email-port',
                        help='SMTP Server tls Port',
                        type=int,
                        default=os.environ.get('EMAIL_PORT',
                                               config.get('EMAIL_PORT')))
    parser.add_argument('--filename',
                        help='Name of the local file in which '
                             'the HTML Email Body is '
                             'saved with --print and --web options',
                        type=str,
                        default=os.environ.get('FILENAME',
                                               config.get('FILENAME')))
    parser.add_argument('--warning-threshold',
                        help='Number of weeks out that upcoming open '
                             'slots will generate a warning',
                        type=int,
                        default=os.environ.get('WARNING_THRESHOLD',
                                               config.get('WARNING_THRESHOLD')))
    parser.add_argument('--message',
                        help='an alternate message string to send',
                        type=str,
                        default=os.environ.get('MESSAGE',
                                               config.get('MESSAGE')))
    args = parser.parse_args()

    x = False
    for k, v in vars(args).items():
        if v is None:
            x = True
            print('ERROR: "{}" MUST BE DEFINED'.format(str.upper(k)))
    if x:
        exit(1)

    template = get_template(file=args.template)
    sched_items = get_sheetsu_items_secure(args.sheetsu_schedule_api_id, args.sheetsu_api_key, args.sheetsu_api_secret)
    nicknames = get_sheetsu_items(args.sheetsu_nickname_api_id)[0]

    if not args.message:
        html, when, upcoming = render_body(sched_items=sched_items,
                                           today=args.date,
                                           template=template,
                                           warning_threshold=args.warning_threshold,
                                           nicknames=nicknames,
                                           band_mappings=config.get(
                                               'BAND_MAPPINGS'))
        if not args.subject:
            args.subject = "KCARC Net: {}, {}".format(when, upcoming)
        text = 'text item to be filled'
    else:
        html = """\
            <html>
              <body>
                <p>
                  {}
                </p>
              </body>
            </html>""".format(args.message)
    text = args.message

    if args.print:
        print(html)
    elif args.web:
        save_html(html=html,
                  filename=args.filename)
        webbrowser.open('file://' + os.path.realpath(args.filename))
    else:
        send_email(server=args.email_server,
                   port=args.email_port,
                   password=args.email_password,
                   sender=args.sender,
                   to=args.to,
                   cc=args.cc,
                   bcc=args.bcc,
                   subject=args.subject,
                   html=html,
                   text=text,
                   attachments=args.attachment)


if __name__ == "__main__":
    main()
