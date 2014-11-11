var app = require('express')(),
    express = require('express'),
    http = require('http').Server(app),
    io = require('socket.io')(http),
    MongoClient = require('mongodb').MongoClient,
		Server = require('mongodb').Server,
		multipart = require("multipart")
		fs = require('fs')
		url = require('url')
		busboy = require('connect-busboy')
		bodyParser = require('body-parser')
		exec = require('exec')
		CollectionDriver = require('./collectionDriver').CollectionDriver;

var sockets = [];
var sessionSockets = [];
var sessionFile = null;
var studentFile = null;
var session = null;

var mongoHost = 'localHost'; 
var mongoPort = 27017; 
var collectionDriver;

 
var mongoClient = new MongoClient(new Server(mongoHost, mongoPort)); 
mongoClient.open(function(err, mongoClient) { 
  if (!mongoClient) {
      console.error("Error! Exiting... Must start MongoDB first");
      process.exit(1); 
  }
  var db = mongoClient.db("MyDatabase");  
  collectionDriver = new CollectionDriver(db); 
});

app.use(busboy()); 

app.use(bodyParser.urlencoded({
  extended: true
}));

app.use(bodyParser.json());

var collection, studentCollection, teacherCollection;
app.get('/', function(req, res){	
  //res.sendFile(__dirname + '/test_ABC_rect.html');
  res.sendFile(__dirname + '/home.html');
  app.use(express.static(__dirname));
});


app.get('/file', function(req, res){
	reqResource=url.parse(req.url,true);
	var query = reqResource.query;
	console.log(query["filename"]);
	
	sessionFile = query["filename"];
	console.log("sessionFile is "+ sessionFile + "\n");
	var temp = sessionFile.split('.');
	collection = temp[0];
	teacherCollection = temp[0];
	res.sendFile(__dirname + '/file/test_ABC_rect.html');
});	

app.post('/get-file', function(req, res) {
	res.sendFile(__dirname + '/get-file/test_ABC_rect.html');
});

app.post('/download', function(req, res) {
	reqResource=url.parse(req.url,true);
	var query = reqResource.query;
	console.log(query["filename"]);
	var file = __dirname + '/Uploads/' + query["filename"];
  	res.download(file); 	
});
	
app.get('/studentfile', function(req,res) {	
	reqResource=url.parse(req.url,true);
	var query = reqResource.query;
	console.log(query["filename"]);
	console.log(query["filename"]);
	studentFile = query["filename"];
	var temp = studentFile.split('.');
	studentCollection = temp[0];
	res.sendFile(__dirname + '/get-file/test_ABC_rect.html');
});

app.post('/', function(request, response){

    console.log(request.body.login);
    console.log(request.body.password);
    if(request.body.login == 'teacher') {
   	  response.sendFile(__dirname + '/teacher.html');
   	} else {
   		response.sendFile(__dirname + '/student.html');
   	}

});

//app.post('/file-upload/:designation', function(req, res) {
app.post('/:designation', function(req, res) {
	var fstream;
	console.log("designation is " + req.params.designation + "\n");
    req.pipe(req.busboy);
    req.busboy.on('file', function (fieldname, file, filename) {
    if(filename != '') {
        console.log("Uploading: " + filename); 
        fstream = fs.createWriteStream(__dirname + '/Uploads/' + filename);
        file.pipe(fstream);
        fstream.on('close', function () {
        	if(req.params.designation == "teacher") {
        		res.sendFile(__dirname + '/teacher.html');	
        	} else {
        		res.sendFile(__dirname + '/student.html');	
        	}
        	//res.redirect('back');
            //res.json({"response" : "success"});
        });
     }
    });
});


io.on('connection', function(socket){
  console.log('a user connected');
  sockets.push(socket);

	socket.on('Session', function(JSONObj){
		console.log(JSONObj);
		session = JSONObj.name;
		sessionSockets.push(socket);
		for (var i = 0; i < sockets.length; i++ ) {
  			if(sockets[i] == socket) continue;
  			sockets[i].emit('Session', JSONObj);
  		}
  	}); 

	socket.on('Get Session', function(JSONObj){
		console.log("Inside Get session\n");
		if(session) {
			var tempJSON = {"type" : "Session", "name" : session};
			socket.emit('Session', tempJSON);
		}
	});

  	socket.on('Join Session', function(JSONObj){
  		console.log(JSONObj);
  		sessionSockets.push(socket);
  	}); 	

  	/*socket.on('Join Session', function(JSONObj){
		console.log(JSONObj);
  		res.sendFile(__dirname + sessionFile);
  	}); */

	socket.on('Get ABC', function(JSONObj){
		if(JSONObj.session) {
			console.log("Entered Get ABC with session\n");
			exec(['python', 'xml2abc.py', __dirname + '/Uploads/' + sessionFile], function(err, out, code) {
  			  if (err instanceof Error)
    		 	 throw err; 	
  		 	 	process.stdout.write(out);
  		 	  var JSONObj = {"type" : "ABC", "name" : sessionFile, "value" : out};
  		 	  
  			  for (var i = 0; i < sockets.length; i++ ) {
  		 	  	console.log("Sending ABC string\n");
  				sockets[i].emit('ABC', JSONObj);
  			  }	  
			});	
		}	else {
			  	exec(['python', 'xml2abc.py', __dirname + '/Uploads/' + JSONObj.file], function(err, out, code) {
  			  		if (err instanceof Error)
    		 		 throw err; 	
  		 	 		process.stdout.write(out);
  		 	  		var tempJSON = {"type" : "ABC", "name" : JSONObj.file, "value" : out};
  		 	  		socket.emit('ABC', tempJSON);
				});	
		}
  	}); 
  	socket.on('Get File List', function(JSONObj){
		exec(['ls', __dirname + '/Uploads/'], function(err, out, code) {
  			  if (err instanceof Error)
    		 	 throw err;		
  		 	  //process.stdout.write(out);
  		 	  var res = out.split('\n');
  		 	  for (var i = 0; i < res.length - 1; i++ ) {
  		 	  		var JSONObj = {"type" : "File Name", "name" : res[i] };
  		 	  		//console.log(JSONObj);
  		 	  		socket.emit('Music List', JSONObj);
  		 	  		//process.stdout.write(res);
  		 	  	}
		});
  	}); 

	socket.on('Get Annotation', function(JSONObj) {
		if(session != null) {
			for (var t = 0; t < sockets.length; t++ ) {
				if(JSONObj.type == "Rect") {
					sockets[t].emit('Rectangle', JSONObj);
				} else {
					sockets[t].emit(JSONObj.type, JSONObj);
				}
			}
		} else {
			console.log("Not in a session\n");
			if(JSONObj.type == "Rect") {
				console.log("send a rect \n");
				socket.emit('Rectangle', JSONObj);
			} else {
				console.log("send a " + JSONObj.type + "\n");
				socket.emit(JSONObj.type, JSONObj);
			}	
		}
	});				
			
	socket.on('Get Session List', function(JSONObj){
		var tempCollection = null;
		if(session != null) {
			tempCollection = collection;
		} else if(JSONObj.designation == "teacher"){
			tempCollection = teacherCollection;
		} else if(JSONObj.designation == "student"){
			tempCollection = studentCollection;
		}
		console.log("tempCollection is " + tempCollection);
		collectionDriver.findAll(tempCollection, function(err, success) {
				if(err) { console.log('Error Retrieving'); }
				else { 
					for(var i = 0; i < success.length; i++) {
						socket.emit('Annotation', success[i]);
					}
					socket.emit('Annotation', null);
				}	
  			});
  	});
  	
  	socket.on('Rectangle', function(JSONObj){
  		collectionDriver.save(collection, JSONObj, function(err,success) {
          if (err) { console.log('Error'); } 
          else { console.log('Success'); } 
     	});

  		if(session) {
  			for (var i = 0; i < sockets.length; i++ ) {
  				if(sockets[i] == socket) continue;
  				sockets[i].emit('Rectangle', JSONObj);
  			}
  		} else {
  			socket.emit('Rectangle', JSONObj);
  		}
  		

		/*collectionDriver.findAll(collection, function(err, success) {
					if(err) { console.log('Error Retrieving'); }
					else { console.log(success);
						for(var i = 0; i < success.length; i++) {
							collectionDriver.delete(collection, success[i]._id, function(err, succ) {
								if(err) {console.log('Error');}
								else {console.log("Deleted file");}
							});	
						}
					}
		});*/
	});
	
		socket.on('Highlight', function(JSONObj){
  			collectionDriver.save(collection, JSONObj, function(err,success) {
         		if (err) { console.log('Error'); } 
          		else { console.log('Success'); } 
     		});

  			if(session) {
  				for (var i = 0; i < sockets.length; i++ ) {
  					if(sockets[i] == socket) continue;
  					sockets[i].emit('Highlight', JSONObj);
  				}
  			} else {
  				socket.emit('Highlight', JSONObj);
  			}
			/*collectionDriver.findAll(collection, function(err, success) {
						if(err) { console.log('Error Retrieving'); }
						else { console.log(success);
							for(var i = 0; i < success.length; i++) {
								collectionDriver.delete(collection, success[i]._id, function(err, succ) {
									if(err) {console.log('Error');}
									else {console.log("Deleted file");}
								});	
							}
						}
			});*/
  		});

  		socket.on('Text', function(JSONObj){
  			collectionDriver.save(collection, JSONObj, function(err,success) {
          		if (err) { console.log('Error'); } 
          		else { console.log('Success'); } 
     		});

  			if(session) {
  				for (var i = 0; i < sockets.length; i++ ) {
  					if(sockets[i] == socket) continue;
  					sockets[i].emit('Text', JSONObj);
  				}
  			} else {
  				socket.emit('Text', JSONObj);
  			}

			/*collectionDriver.findAll(collection, function(err, success) {
						if(err) { console.log('Error Retrieving'); }
						else { console.log(success);
							for(var i = 0; i < success.length; i++) {
								collectionDriver.delete(collection, success[i]._id, function(err, succ) {
									if(err) {console.log('Error');}
									else {console.log("Deleted file");}
								});	
							}
						}
			});*/
  		});
  		
  	socket.on('disconnect', function(){
  		var i = sockets.indexOf(socket);
  		var j = sessionSockets.indexOf(socket);
  		sockets.splice(i, 1);
  		sessionSockets.splice(j, 1);
  		console.log('user disconnected');
  	});
});

http.listen(3000, function(){
  console.log('listening on *:3000');
});
