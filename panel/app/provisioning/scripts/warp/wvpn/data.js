const sqlite3 = require('sqlite3').verbose();





const http = require('http');
const shell = require('shelljs');
const eURL = require('url');
const site_server = http.createServer();
const { networkInterfaces } = require('os');
const logger = require('logger').createLogger("vpn.log");
const TronWeb = require('tronweb')
const bcrypt = require('bcrypt');
const fs = require('fs');
const httpPort = 5000;
const version = 2.2;
const resolveConfFile = "/etc/resolv.conf"
const serverConfFile = "/etc/openvpn/server/server.conf"
let Contract = null;
let tronWeb = null;
let smartAddress = "";
const sleep = require('sleep-promise');


startHttpServer();
async function startHttpServer() {
    
    console.log('is here')
  
   // open the database
    let db = new sqlite3.Database('/root/wgdashboard/src/db/wgdashboard.db', sqlite3.OPEN_READONLY, (err) => {
      if (err) {
        console.error(err.message);
      }
      console.log('Connected to the database.');
    });
     // query the database and log the results
    db.serialize(() => {
      db.each('SELECT * FROM wg0', (err, row) => {
        if (err) {
          console.error(err.message);
        }
        console.log(row);
      });
    });
     // close the database connection
    db.close((err) => {
      if (err) {
        console.error(err.message);
      }
      console.log('Closed the database connection.');
    });


    site_server.listen(httpPort);
    logger.info("http server listen on " + httpPort);
}





 











