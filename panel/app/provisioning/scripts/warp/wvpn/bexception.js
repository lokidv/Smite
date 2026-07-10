class bexception extends Error{

    constructor(msg, success, code) {


        super();
        this.msg = msg;
        this.success = (success !== false);
        this.code = (code ? code : 200);
    }
}

module.exports = bexception;