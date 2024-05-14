// Black Ostrich  JavaScript Regex Proxy

// RegExp.test
// String.match
// String.search
// RegExp.exec

regex_array = []

let originalBORegExpTest = window.RegExp.prototype.test;

(function(proxied) {
window.RegExp.prototype.test = function(x) {

// console.log("Regex test: " + x + " Pattern: " + this);
regex_array.push( [this.toString(), x] );

return originalBORegExpTest.apply(this, [x])
};
})(window.RegExp.prototype.test);

// MATCH 
let originalBORegExpMatch = window.String.prototype.match;

(function(proxied) {
window.String.prototype.match = function(x) {

// console.log("String match: " + this + " Pattern: " + x);
regex_array.push( [x.toString(), this.toString()] );

return originalBORegExpMatch.apply(this, [x])
};
})(window.String.prototype.match);

// string search 

let originalBOStringSearch = window.String.prototype.search;

(function(proxied) {
window.String.prototype.search = function(x) {

// console.log("String search: " + this + " Pattern: " + x);
regex_array.push( [x.toString(), this.toString()] );

return originalBORegExpMatch.apply(this, [x])
};
})(window.String.prototype.search);


// re.exec
let originalBORegExpExec = window.RegExp.prototype.exec;

(function(proxied) {
window.RegExp.prototype.exec = function(x) {

// console.log("RegEXP EXEC match: " + x + " Pattern: " + this);
//console.log();
regex_array.push( [this.toString(), x.toString()] );

return originalBORegExpExec.apply(this, [x])
};
})(window.RegExp.prototype.exec);







